from __future__ import annotations

import collections
import inspect
import itertools
import json
import operator
import re
import shlex
import typing

import click


if typing.TYPE_CHECKING:
    from collections.abc import Iterable, Sequence, Mapping, Iterator
    from typing import Any, Callable, IO


Undefined = object()


class classproperty:
    """A simplified @property decorator for class methods."""

    def __init__(self, func):
        self.fget = func

    def __get__(self, instance, owner):
        return self.fget(owner)


class ClickSearchException(click.ClickException):
    """Base clicksearch excepton class."""

    pass


class MissingField(ClickSearchException):
    """
    Exception raised when a `FieldBase` instance cannot find its value in a
    data set.
    """

    pass


class ReaderBase(collections.abc.Iterable):
    """Base class for reader objects."""

    def __init__(self, options: dict):
        pass

    def __iter__(self) -> Iterator[Mapping]:
        raise NotImplementedError

    @classmethod
    def make_params(cls) -> Iterable[click.Parameter]:
        """Yields all standard options required by the reader."""
        return []


class FileReader(ReaderBase):
    """Reader that reads from files specified as CLI parameters."""

    file_parameter = "file"

    def __init__(self, options: dict):
        self.filenames = options[self.file_parameter] or []

    @classmethod
    def make_params(cls) -> Iterable[click.Parameter]:
        """Yields all standard options offered by the CLI."""
        yield click.Argument([cls.file_parameter], nargs=-1)

    def files(self) -> Iterable[IO]:
        """
        Yields file handles for the file names in `self.filenames`. Raises
        variants of `OSError` if a file name cannot be opened for reading.
        """
        try:
            for filename in self.filenames:
                with open(filename, "r") as fd:
                    yield fd
        except FileNotFoundError:
            raise click.FileError(filename, f"File not found: {filename}")
        except PermissionError:
            raise click.FileError(filename, f"Permission denied: {filename}")
        except IsADirectoryError:
            raise click.FileError(filename, f"Not a file: {filename}")
        except OSError as exc:
            raise click.FileError(filename, str(exc))


class JsonReader(FileReader):
    """
    Reader class that reads items from JSON files. The JSON data is expected
    to be a list of objects.
    """

    def __iter__(self) -> Iterator[Mapping]:
        """Yields items from files in `self.files`."""
        for fd in self.files():
            doc = json.load(fd)
            for item in doc:
                yield item


class JsonLineReader(FileReader):
    """
    Reader class that reads items from files where every line is a JSON
    object.
    """

    def __iter__(self) -> Iterator[Mapping]:
        """Yields items from files in `self.files`."""
        for fd in self.files():
            for line in fd:
                yield json.loads(line.rstrip())


class ClickSearchContext(click.Context):
    """
    Default clicksearch `Context` class. In addition to the base
    `click.Context` class, this adds a datastructure used to collect all field
    filter arguments specified during an execution.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fieldfilterargs: dict[
            FieldBase, dict[ClickSearchOption, Sequence[Any]]
        ] = collections.defaultdict(dict)
        self.autofilter_fields = None


class ClickSearchCommand(click.Command):
    """
    Default clicksearch `Command` class. Holds a reference to the `ModelBase`
    class that defines the data items to operate on.
    """

    context_class = ClickSearchContext

    def __init__(self, *args, model: type[ModelBase], reader: Callable, **kwargs):
        if "help" not in kwargs:
            kwargs["help"] = model.__doc__
        super().__init__(*args, **kwargs)
        self.model = model
        self.reader = reader
        self.parser: click.parser.OptionParser | None = None

    def make_parser(self, ctx: click.Context) -> click.parser.OptionParser:
        """Save the returned parser instance on `self`."""
        self.parser = super().make_parser(ctx)
        return self.parser

    def format_options(self, ctx: click.Context, formatter: click.HelpFormatter):
        """
        Writes separate sections of options and field filters into the
        `formatter` if they exist.
        """
        opts = []
        fields = []
        for param in self.get_params(ctx):
            rv = param.get_help_record(ctx)
            if rv is not None:
                if isinstance(param, ClickSearchOption):
                    fields.append(rv)
                else:
                    opts.append(rv)

        if opts:
            with formatter.section("Options"):
                formatter.write_dl(opts)

        if fields:
            with formatter.section("Field filters"):
                formatter.write_dl(fields)

    def format_epilog(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        """Writes the field type help texts, and then the epilog."""
        types = set(
            (param.type.get_metavar(), param.type.get_metavar_help())
            for param in self.get_params(ctx)
            if param.type
            and isinstance(param.type, FieldBase)
            and not (isinstance(param, click.Option) and param.is_flag)
        )
        items = sorted((k, v) for k, v in types if k and v)
        if items:
            with formatter.section("Where"):
                formatter.write_dl(items)
        super().format_epilog(ctx, formatter)


class ClickSearchOption(click.Option):
    """
    Default clicksearch `Option` class for filter options. Holds a reference
    to the function used for filtering data items.
    """

    def __init__(
        self,
        *args,
        field: FieldBase,
        func: Callable | None,
        multiple: bool = True,
        **kwargs,
    ):
        kwargs["type"] = field
        kwargs["multiple"] = multiple
        super(ClickSearchOption, self).__init__(*args, **kwargs)
        self.field = field
        self.func = func

    def process_value(self, ctx: ClickSearchContext, value: Any) -> Any:  # type: ignore
        """
        In addition to processing the value, also register the use of this
        option in `ctx.fieldfilterargs`.
        """
        value = super().process_value(ctx, value)
        if not self.value_is_missing(value):
            ctx.fieldfilterargs[self.field][self] = value if self.multiple else [value]
        return value


class ClickSearchRedirectArgument(click.Argument):
    def __init__(self, redirect_to: click.Parameter):
        self.redirect_to = redirect_to
        super().__init__(
            ["_arg"],
            metavar=f"[{redirect_to.type.get_metavar(redirect_to)}]...",
            nargs=-1,
        )

    def process_value(self, ctx: ClickSearchContext, value: Any) -> Any:  # type: ignore
        """Redirect the use of this argument to the marked option."""
        return self.redirect_to.process_value(ctx, value)


class ModelBase:
    """Base class for models used to define the data items to operate on."""

    __version__: str | None = None

    _standalone_mode = True
    _command_name: str = "Base command"
    _command_cls: type[ClickSearchCommand] = ClickSearchCommand
    _option_cls: type[ClickSearchOption] = ClickSearchOption
    _reader_cls: type[ReaderBase] = JsonLineReader
    _fields: dict[type[ModelBase], dict[str, FieldBase]] = collections.defaultdict(dict)

    @classmethod
    def register_field(cls, name: str, field: FieldBase):
        """Register a `field` by `name` on this model."""
        cls._fields[cls][name] = field
        if len(cls._fields[cls]) == 1:
            cls.register_first_field(name, field)

    @classmethod
    def register_first_field(cls, name: str, field: FieldBase):
        """
        Set up specific setting for the first `field` registered on this model.
        """
        if field.styles is None:
            field.styles = {}
        field.styles.setdefault("fg", "cyan")
        field.styles.setdefault("bold", True)
        if field.unlabeled is Undefined:
            field.unlabeled = True

    @classmethod
    def resolve_fields(cls) -> Iterable[FieldBase]:
        """
        Yields all fields registered on this model. Fields on parent models
        are included but ordered after the child model, and any overloaded
        field names are skipped.
        """
        seen = set()
        for ancestor in cls.__mro__:
            if not issubclass(ancestor, ModelBase):
                break
            for name, field in cls._fields[ancestor].items():
                if name not in seen:
                    yield field
                    seen.add(name)

    @classmethod
    def resolve_fieldfilteroptions(cls) -> Iterable[click.Parameter]:
        """
        Yields tuples with all `ClickSearchOption` objects registered for the
        fields on this model. Searches parent classes but skips overloaded
        field names.
        """
        for field in cls.resolve_fields():
            for i, opt in enumerate(field.fieldfilteroptions):
                if i == 0 and field.redirect_args:
                    yield ClickSearchRedirectArgument(opt)
                yield opt

    @classmethod
    def make_command(cls, reader: Callable) -> click.Command:
        """Returns the `click.Command` object used to run the CLI."""
        cmdobj = cls._command_cls(
            cls._command_name,
            callback=click.pass_context(cls.main),  # type: ignore
            model=cls,
            reader=reader,
        )
        if hasattr(reader, "make_params"):
            cmdobj.params.extend(reader.make_params())
        cmdobj.params.extend(cls.make_params())
        cmdobj.params.extend(cls.resolve_fieldfilteroptions())
        click.version_option(cls.__version__)(cmdobj)
        return cmdobj

    @classmethod
    def make_params(cls) -> Iterable[click.Parameter]:
        """Yields all standard options offered by the CLI."""
        fieldmap = {field.helpname: field for field in cls.resolve_fields()}
        yield click.Option(["--verbose", "-v"], count=True, help="Show more data.")
        yield click.Option(
            ["--brief"],
            is_flag=True,
            help="Show one line of data, regardless the level of verbose.",
        )
        yield click.Option(
            ["--long"],
            is_flag=True,
            help="Show multiple lines of data, regardless the level of verbose.",
        )
        yield click.Option(
            ["--show"],
            help=(
                "Show given field only. Can be repeated to show multiple fields "
                "in given order."
            ),
            multiple=True,
            type=FieldChoice(fieldmap),
        )
        yield click.Option(
            ["--case"], is_flag=True, help="Use case sensitive filtering."
        )
        yield click.Option(["--exact"], is_flag=True, help="Use exact match filtering.")
        yield click.Option(
            ["--regex"], is_flag=True, help="Use regular rexpressions when filtering."
        )
        yield click.Option(
            ["--or"],
            help=(
                "Treat multiple tests for given field with logical disjunction, "
                "i.e. OR-logic instead of AND-logic."
            ),
            multiple=True,
            type=FieldChoice(fieldmap),
        )
        yield click.Option(
            ["--inclusive"],
            is_flag=True,
            help=(
                "Treat multiple tests for different fields with logical disjunction, "
                "i.e. OR-logic instead of AND-logic."
            ),
        )
        yield click.Option(
            ["--sort"],
            help="Sort results by given field.",
            multiple=True,
            type=FieldChoice(fieldmap),
        )
        yield click.Option(
            ["--desc"], is_flag=True, help="Sort results in descending order."
        )
        yield click.Option(
            ["--group"],
            help="Group results by given field.",
            multiple=True,
            type=FieldChoice(fieldmap),
        )
        yield click.Option(
            ["--count"],
            help="Print a breakdown of all values for given field.",
            multiple=True,
            type=FieldChoice(fieldmap),
        )

    @classmethod
    def cli(
        cls,
        args: str | Iterable[str] | None = None,
        reader: Callable | None = None,
        **kwargs: Any,
    ):
        """Run the CLI."""
        if isinstance(args, str):
            import shlex

            args = shlex.split(args)
        kwargs.setdefault("standalone_mode", cls._standalone_mode)
        try:
            cls.make_command(reader or cls._reader_cls)(args, **kwargs)
        except click.ClickException as e:
            if kwargs["standalone_mode"]:
                raise
            # We are in test mode and want to show the error without exiting
            # the REPL
            e.show()

    @classmethod
    def main(cls, ctx: ClickSearchContext, **options: Any):
        """Main program flow used by the CLI."""

        # Pre-process all the options
        cls.preprocess_fieldfilterargs(ctx.fieldfilterargs, options)

        # Collect all referenced `autofilter` fields.
        ctx.autofilter_fields = set(
            field
            for field in itertools.chain(
                options["count"],
                options["sort"],
                options["group"],
                options["show"],
            )
            if field.autofilter
        )

        # Set up an iterable over all the items
        if isinstance(ctx.command, ClickSearchCommand):
            items = ctx.command.reader(options)

        # Filter the items
        items = cls.filter_items(ctx, items, options)

        # Sort the items
        items = cls.sort_items(items, options)

        # Adjust verbose based on numer of items found
        items = cls.adjust_verbose(items, options)

        # Collect the fields we are interested in printing
        if options["show"] and cls._fields[cls]:
            title_field, *_ = cls._fields[cls].values()
            if title_field in options["show"]:
                show_fields = options["show"]
            else:
                show_fields = [title_field, *options["show"]]
            show_explicit = True
        else:
            show_fields = list(cls.collect_visible_fields(options))
            show_explicit = False

        # Prefer verbose output if any explicit field is not meant for brief
        if (
            show_explicit
            and options["verbose"] == 0
            and not options["brief"]
            and any(field.verbosity for field in show_fields)
        ):
            options["verbose"] = 1

        # Set print_func based on verbosity
        print_long = cls.print_long
        print_brief = cls.print_brief
        if options["verbose"] < 0:
            print_func = None
        elif options["long"] or (options["verbose"] and not options["brief"]):
            print_func = print_long
        else:
            print_func = print_brief

        # Set up info for print group headers
        current_group: list[Any] | None = None
        group_fields: Iterable[FieldBase] | None = None
        if options["group"]:
            group_fields = options["group"]
            current_group = []

        # Set up counter
        item_count = 0
        counts: dict[FieldBase, dict[str, int]] = collections.defaultdict(
            collections.Counter
        )

        # Print each item
        for item in items:
            # Count stuff
            item_count += 1
            for field in options["count"]:
                field.count(item, counts[field])

            # If verbosity dictates we're just counting stuff, we're done
            if print_func is None:
                continue

            # Print group header
            if group_fields:
                next_group = [field.fetch(item, None) for field in group_fields]
                if current_group != next_group:
                    if current_group and print_func is print_brief:
                        click.echo()
                    header = " | ".join(
                        click.unstyle(field.format_brief(value, show=True))
                        for field, value in zip(group_fields, next_group)
                    )
                    click.secho(f"[ {header} ]", fg="yellow", bold=True)
                    click.echo()
                    current_group = next_group

            # Print the item
            print_func(show_fields, item, options, show=show_explicit)

        # Print breakdown counts
        if print_func is print_brief:
            click.echo()
        cls.print_counts(counts, item_count)

    @classmethod
    def preprocess_fieldfilterargs(
        cls,
        fieldfilterargs: dict[FieldBase, dict[ClickSearchOption, Sequence[Any]]],
        options: dict,
    ):
        """
        Pre-processes all data in `fieldfilterargs` after we have received all
        options. Actual pre-processing is delegated to
        `FieldBase.preprocess_filterarg`.
        """
        for field, filteropts in fieldfilterargs.items():
            for filteropt, filterargs in filteropts.items():
                fieldfilterargs[field][filteropt] = [
                    field.preprocess_filterarg(filterarg, filteropt, options)
                    for filterarg in filterargs
                ]

    @classmethod
    def filter_items(
        cls, ctx: ClickSearchContext, items: Iterable[Mapping], options: dict
    ) -> Iterable[Mapping]:
        """
        Yields the items that pass `cls.test_item` and has valid
        values for all the fields referenced by
        `ctx.autofilter_fields`.
        """
        for item in items:
            if cls.test_item(ctx, item, options):
                for field in ctx.autofilter_fields:
                    try:
                        field.fetch(item)
                    except MissingField:
                        break
                else:
                    yield item

    @classmethod
    def test_item(cls, ctx: ClickSearchContext, item: Mapping, options: dict) -> bool:
        """
        Returns `True` if `item` passes all filter options used, otherwise
        `False`.
        """
        inclusive = bool(options["inclusive"])
        for field, filteropts in ctx.fieldfilterargs.items():
            try:
                value = field.fetch(item)
                any_or_all = any if field.inclusive or field in options["or"] else all
                result = any_or_all(
                    any_or_all(
                        filteropt.func(field, filterarg, value, options)
                        for filterarg in filterargs
                    )
                    for filteropt, filterargs in filteropts.items()
                    if filteropt.func
                )
            except MissingField:
                result = False
            if result is inclusive:
                return result
        return not inclusive

    @classmethod
    def sort_items(cls, items: Iterable[Mapping], options: dict) -> Iterable[Mapping]:
        """
        Returns `items` sorted according to the --group and --sort `options`.
        """
        sort_fields = options["group"] + options["sort"]
        if sort_fields:

            def key(item):
                return [field.sortkey(item) for field in sort_fields]

            items = sorted(items, key=key, reverse=options["desc"])
        return items

    @classmethod
    def adjust_verbose(cls, items, options):
        """
        Adjusts the verbosity based on number of `items` and `options`.
        Returns `items` again (since we may have to tamper with when an
        iterator).
        """
        if options["brief"]:
            options["verbose"] = 0
        elif not options["long"]:
            if isinstance(items, list):
                if len(items) == 1:
                    options["verbose"] += 1
            else:
                item_1 = item_2 = None
                try:
                    item_1 = next(items)
                    item_2 = next(items)
                except StopIteration:
                    if item_1 is None:
                        items = []
                    elif item_2 is None:
                        items = [item_1]
                        options["verbose"] += 1
                else:
                    items = itertools.chain([item_1, item_2], items)
        if options["count"]:
            options["verbose"] -= 1
        return items

    @classmethod
    def collect_visible_fields(cls, options):
        """Yields all fields that should be considered for printing."""
        verbose = options["verbose"]
        for field in cls.resolve_fields():
            if field.verbosity is None or verbose < field.verbosity:
                continue
            yield field

    @classmethod
    def print_brief(
        cls, fields: list[FieldBase], item: Mapping, options: dict, show: bool = False
    ):
        """Prints a one-line representation of `item`."""
        first = True
        for field in fields:
            try:
                value = field.fetch(item)
            except MissingField:
                continue
            value = field.format_brief(value, show=show)
            if not value:
                continue
            if first:
                if len(fields) > 1:
                    if field.styles:
                        value += click.style(": ", **field.styles)
                    else:
                        value += ": "
                first = False
            elif value.endswith(".") or value.endswith(".\x1b[0m"):
                value += " "
            else:
                value += ". "
            click.echo(value, nl=False)
        click.echo()

    @classmethod
    def print_long(
        cls, fields: list[FieldBase], item: Mapping, options: dict, show: bool = False
    ):
        """Prints a multi-line representation of `item`."""
        for field in fields:
            try:
                value = field.fetch(item)
            except MissingField:
                continue
            value = field.format_long(value, show=show)
            if not value:
                continue
            click.echo(value)
        click.echo()

    @classmethod
    def print_counts(cls, counts: dict[FieldBase, dict[str, int]], item_count: int):
        """Prints `counts` breakdowns."""
        widths = {
            value: len(click.unstyle(value))
            for breakdown in counts.values()
            for value in breakdown
        }
        colwidth = max(widths.values()) + 1 if widths else 0
        for field, breakdown in counts.items():
            click.secho(f"[ {field.realname} counts ]", fg="green", bold=True)
            click.echo()
            for value, count in sorted(
                breakdown.items(), key=operator.itemgetter(1), reverse=True
            ):
                click.echo(
                    click.style(
                        f"{value}:" + " " * (colwidth - widths[value]), bold=True
                    )
                    + str(count)
                )
            click.echo()
        click.echo(
            click.style("Total count: ", fg="green", bold=True) + str(item_count)
        )


class fieldfilter:
    """
    Decorator to mark a `FieldBase` class method as a field filter.
    Type signature matches the `click.option` decorator.
    """

    def __init__(self, *param_decls, **kwargs):
        self.kwargs = {"param_decls": param_decls, **kwargs}
        self.func: Callable | None = None  # Set when called the first time

    def __set_name__(self, owner: type[FieldBase], name: str):
        """Register this field filter to the `owner` field."""
        owner.register_fieldfilter(self)
        setattr(owner, name, self.func)

    def __call__(self, func: Callable):
        """Register the decorated `func` as a field filter."""
        self.func = func
        if "help" not in self.kwargs and self.func.__doc__:
            self.kwargs["help"] = inspect.cleandoc(self.func.__doc__)
        return self

    @property
    def name(self):
        """
        Return the name of this fieldfilter, the same as the decorated
        function.
        """
        return self.func.__name__ if self.func else None

    def format_kwargs(self, optname: str, helpname: str, optalias: str | None) -> dict:
        """Return a copy of the field filter kwargs with formatted parameters."""
        kwargs = self.kwargs.copy()
        if optalias:
            kwargs["param_decls"] = (optalias, *kwargs["param_decls"])
        kwargs["param_decls"] = tuple(
            arg.format(optname=optname) for arg in kwargs["param_decls"]
        )
        if "help" in kwargs:
            kwargs["help"] = kwargs["help"].format(helpname=helpname)
        return kwargs


class FieldBase(click.ParamType):
    """
    Base class for the properties that define the fields on `ModelBase`
    classes.
    """

    name: str

    _fieldfilters: dict[type[FieldBase], list[fieldfilter]] = collections.defaultdict(
        list
    )

    def __init__(
        self,
        default: Any | type = MissingField,
        inclusive: bool = False,
        skip_filters: Iterable[fieldfilter] | None = None,
        keyname: str | None = None,
        optname: str | None = None,
        optalias: str | None = None,
        realname: str | None = None,
        helpname: str | None = None,
        typename: str | None = None,
        verbosity: int | None = 0,
        unlabeled: bool | object = Undefined,
        brief_format: str | None = None,
        styles: dict | None = None,
        redirect_args: bool = False,
        autofilter: bool = False,
    ):
        self.default = default
        self.inclusive = inclusive
        self.skip_filters = skip_filters
        self.keyname = keyname
        self.optname = optname
        self.optalias = optalias
        self.realname = realname
        self.helpname = helpname
        self.typename = typename
        self.verbosity = verbosity
        self.unlabeled = unlabeled
        self.brief_format = brief_format
        self.styles = styles
        self.redirect_args = redirect_args
        self.autofilter = autofilter

        # Set when assigned to a model
        self.model: type[ModelBase] = None  # type: ignore
        self.fieldfilteroptions: list[ClickSearchOption] = []

    def __set_name__(self, owner: type[ModelBase], name: str):
        """
        Registers this `FieldBase` instance on a `owner` `ModelBase` class
        under the given `name`.
        """
        self.model = owner
        if self.keyname is None:
            self.keyname = name
        if self.realname is None:
            self.realname = name.replace("_", " ").title()
        if self.helpname is None:
            self.helpname = self.realname.lower()
        if self.optname is None:
            self.optname = self.realname.lower().replace(" ", "-")
        self.model.register_field(name, self)
        # Create the Option objects for all field filters
        for i, ffilter in enumerate(self.resolve_fieldfilters()):
            self.fieldfilteroptions.append(
                self.model._option_cls(
                    func=ffilter.func,  # type: ignore
                    field=self,
                    **ffilter.format_kwargs(
                        optname=self.optname,
                        helpname=self.helpname,
                        optalias=self.optalias if i == 0 else None,
                    ),
                )
            )

    @classmethod
    def register_fieldfilter(cls, ffilter: fieldfilter):
        """Registers a fieldfilter `ffilter`."""
        cls.fieldfilters.append(ffilter)

    @classproperty
    def fieldfilters(cls) -> list[fieldfilter]:
        """Return all field filters registered for this class."""
        return cls._fieldfilters[cls]  # type: ignore

    def resolve_fieldfilters(self) -> Iterable[fieldfilter]:
        """
        Yields all filters defined with the `fieldfilter` decorator on this
        field and its ancestors. Overloaded filters are only yielded once.
        """
        seen = set()
        for ancestor in self.__class__.__mro__:
            if not issubclass(ancestor, FieldBase):
                break
            for ffilter in ancestor.fieldfilters:
                if ffilter.name in seen:
                    continue
                if self.skip_filters and ffilter.func in self.skip_filters:
                    continue
                yield ffilter
                seen.add(ffilter.name)

    def convert(
        self,
        filterarg: Any,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> Any:
        """
        Converts a filter argument `filterarg` for this field and return the
        new value. This calls `validate` and handles any `TypeError` or
        `ValueError` raised by re-raising a `click.BadParameter` exception.
        """
        try:
            return self.validate(filterarg)
        except (ValueError, TypeError):
            raise click.BadParameter(str(filterarg), ctx=ctx, param=param)

    def preprocess_filterarg(
        self, filterarg: Any, opt: click.Parameter, options: dict
    ) -> Any:
        """Pre-processes a `filterarg` for an `opt` used as a filter for this field."""
        return filterarg

    def validate(self, value: Any) -> Any:
        """Validates `value` and return a possibly converted value."""
        return value

    def fetch(self, item: Mapping, default: Any | type = MissingField) -> Any:
        """
        Returns this field's value in `item`.
        * If `item` has no value for this field and `default` is given, then
          `default` is returned instead. Otherwise a `MissingField` exception
          is raised.
        * If this field has overloaded the `validate` method, it may raise an
          exception if the value cannot be converted by that method.
        """
        try:
            value = item[self.keyname]
            if self.is_missing(value) and value != default:
                raise MissingField(f"Value missing: {self.keyname}")
        except KeyError:
            if default is MissingField:
                if self.default is MissingField:
                    raise MissingField(f"Value missing: {self.keyname}")
                else:
                    value = self.default
            else:
                value = default
        return self.validate(value)

    def is_missing(self, value: Any) -> bool:
        """
        Return `True` if the value of this field indicates that it is infact
        missing, otherwise return `False`.
        """
        return value is None

    def sortkey(self, item: Mapping) -> Any:
        """
        Returns a comparable-type version of this field's value in `item`,
        used for sorting.
        """
        try:
            return self.fetch(item)
        except MissingField:
            return self.format_null()

    def format_value(self, value: Any) -> str | None:
        """Return a string representation of `value`."""
        if value == "":
            return value
        if value is None:
            return self.format_null()
        return self.style(str(value))

    def format_null(self) -> str | None:
        """Return a string representation of a `None` value, if any."""
        return f"No {self.realname}"

    def format_brief(self, value: Any, show: bool = False) -> str:
        """
        Return a brief formatted version of `value` for this field. If `show`
        is `True`, the field was explicitly requested to be displayed.
        """
        if value is None:
            return self.format_null()
        value = self.format_value(value)
        if self.brief_format:
            value = self.brief_format.format(name=self.realname, value=value)
        return value

    def format_long(self, value: Any, show: bool = False) -> str:
        """
        Returns a long (single line) formatted version of `value` for this
        field. If `show` is `True`, the field was explicitly requested to be
        displayed.
        """
        value = self.format_value(value)
        if self.unlabeled is True:
            return value
        return f"{self.realname}: {value}"

    def style(self, value: Any) -> str:
        """Returns a styled `value` for this field."""
        if self.styles:
            return click.style(value, **self.styles)
        return value

    def count(self, item: Mapping, counts: collections.Counter):
        """Increments the `counts` count of this field's value in `item` by 1."""
        try:
            counts[self.format_brief(self.fetch(item), show=True)] += 1
        except MissingField:
            pass

    def get_metavar(self, *_):
        """Return the name of the option argument for this field used in `--help`."""
        return self.typename or self.name

    def get_metavar_help(self):
        """
        Return a longer description of the option argument for this field used
        in `--help`.
        """
        if self.__doc__:
            return inspect.cleandoc(self.__doc__)
        return None


class Number(FieldBase):
    """Class for defining a numeric field on a model."""

    name = "NUMBER"
    operators = [
        ("==", operator.eq),
        ("=", operator.eq),
        ("!=", operator.ne),
        ("!", operator.ne),
        ("<=", operator.le),
        ("<", operator.lt),
        (">=", operator.ge),
        (">", operator.gt),
    ]

    def __init__(
        self,
        *args,
        brief_format: str | None = None,
        unlabeled: bool = False,
        specials: list[str] | None = None,
        **kwargs,
    ):
        if not brief_format and not unlabeled:
            brief_format = "{name} {value}"
        super().__init__(
            *args,
            brief_format=brief_format,  # type: ignore
            unlabeled=unlabeled,
            **kwargs,
        )
        self.specials = specials

    def get_metavar_help(self):
        """
        Return a longer description of the option argument for this field used
        in `--help`.
        """
        return (
            "A number optionally prefixed by one of the supported comparison "
            f"operators: {', '.join(op[0] for op in self.operators)}. With "
            "== being the default if only a number is given."
        )

    def convert(
        self,
        filterarg: Any,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> Any:
        """
        Converts `filterarg` to a function that implements the comparison. If
        `filterarg` is just a legal value, the default comparison is
        equality.
        """
        filterarg = filterarg.strip()
        for operator_prefix, op in self.operators:
            if filterarg.startswith(operator_prefix):
                filterarg = filterarg[len(operator_prefix) :].lstrip()
                break
        else:
            op = operator.eq
        filterarg = super(Number, self).convert(filterarg, param, ctx)

        def compare(value):
            try:
                return op(value, filterarg)
            except TypeError:
                return False

        return compare

    def validate(self, value: Any) -> Any:
        """
        Converts `value` to an `int` or `float` and return it.
        * If `value` is `None` or if it matches any of the `specials` defined
          for this field, then `value` is returned without conversion.
        * If `value` cannot be converted, a `TypeError` or `ValueError` is
          raised.
        """
        value = super().validate(value)
        if self.specials and value in self.specials:
            return value
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return float(value)

    def sortkey(self, item: Mapping) -> Any:
        """
        Returns a comparable-type version of this field's value in `item`, used
        for sorting. For `Number` objects this is guaranteed to be an `int`
        or `float`.
        """
        try:
            value = self.fetch(item)
        except MissingField:
            return -2
        if isinstance(value, (int, float)):
            return value
        return -1

    @fieldfilter(
        "--{optname}", help="Filter on matching {helpname} (number comparison)."
    )
    def filter_number(self, arg: Callable, value: Any, options: dict) -> bool:
        """
        Returns the result of calling `arg` with `value`. Where `arg` is the
        comparator function provided by `convert`.
        """
        if value is None:
            return False
        return arg(value)


class Count(Number):
    """
    Class for defining a countable field on a model. This differs from a
    `Number` field only by how it is presented in the brief format. If the name
    of the field is something you can put a count in front of, then it is
    probably a `Count` rather than a `Number`.
    """

    def __init__(
        self,
        *args,
        brief_format: str | None = None,
        unlabeled: bool = False,
        **kwargs,
    ):
        if not brief_format and not unlabeled:
            brief_format = "{value} {name}"
        super().__init__(
            *args, brief_format=brief_format, unlabeled=unlabeled, **kwargs
        )


class Text(FieldBase):
    """Class for defining a text field on a model."""

    name = "TEXT"

    NEGATE_FLAG = 512

    def get_metavar_help(self):
        """
        Return a longer description of the option argument for this field used
        in `--help`.
        """
        return (
            "A text partially matching the field value. The --case, --regex and "
            "--exact options can be applied. If prefixed with ! the match is negated."
        )

    def preprocess_filterarg(
        self, filterarg: Any, opt: click.Parameter, options: dict
    ) -> Any | re.Pattern:
        """
        Pre-processes `filterarg` for comparison against `Text` field
        values, depending on the `options` used.
        """
        flags = 0
        if not options["case"]:
            filterarg = filterarg.lower()
        if options["regex"]:
            if filterarg.startswith("!"):
                if not filterarg.startswith("!!"):
                    flags |= self.NEGATE_FLAG
                filterarg = filterarg[1:]
            if options["exact"]:
                filterarg = f"^{filterarg}$"
            try:
                filterarg = re.compile(filterarg, flags)
            except re.error:
                raise click.BadParameter("Invalid regular expression", param=opt)
        return filterarg

    def sortkey(self, item: Mapping) -> Any:
        """
        Returns a comparable-type version of this field's value in `item`, used
        for sorting. For `Text` objects this is guaranteed to be of type
        `str`.
        """
        try:
            return self.fetch(item)
        except MissingField:
            return ""

    @fieldfilter("--{optname}", help="Filter on matching {helpname}.")
    def filter_text(self, arg: Any, value: Any, options: dict) -> bool:
        """
        Returns `True` if `arg` matches `value`, depending on `options`,
        otherwise `False`.
        """
        negate = False
        if not options["case"]:
            value = value.lower()
        if options["regex"]:
            result = bool(arg.search(value))
            negate = bool(arg.flags & self.NEGATE_FLAG)
        else:
            if arg.startswith("!"):
                negate = not arg.startswith("!!")
                arg = arg[1:]
            if options["exact"]:
                result = value and arg == value
            else:
                result = value and arg in value
        return bool(result) ^ negate


class DelimitedText(Text):
    """
    Class for defining a multi-value text field on a model. The values of this
    field can include a given string delimiter, so that when split by this
    delimiter, each split part is treated individually.
    """

    def __init__(self, delimiter: str = ",", **kwargs):
        super().__init__(**kwargs)
        self.delimiter = delimiter

    def parts(self, value: str) -> Iterable[str]:
        """Yields each individual part of the `DelimitedText`."""
        for part in value.split(self.delimiter):
            part = part.strip()
            if part:
                yield part

    def count(self, item: Mapping, counts: collections.Counter):
        """
        Increments the count of each part in the `DelimitedText`
        individually.
        """
        try:
            for part in self.parts(self.fetch(item)):
                counts[part] += 1
        except MissingField:
            pass

    @fieldfilter("--{optname}", help="Filter on matching {helpname}.")
    def filter_text(self, arg: Any, value: Any, options: dict) -> bool:
        """
        Returns `True` if `arg` matches any part of the separated `value`,
        depending on `options`, otherwise `False`.
        """
        if options["regex"]:
            negate = bool(arg.flags & self.NEGATE_FLAG)
        else:
            negate = arg.startswith("!") and not arg.startswith("!!")
        any_or_all = all if negate else any
        return any_or_all(
            super(DelimitedText, self).filter_text(arg, part, options)
            for part in self.parts(value)
        )


class Flag(FieldBase):
    """Class for defining a boolean field on a model."""

    name = "FLAG"

    def __init__(
        self, truename: str | None = None, falsename: str | None = None, **kwargs
    ):
        super().__init__(**kwargs)
        self.truename = truename
        self.falsename = falsename

    def __set_name__(self, owner: type[ModelBase], name: str):
        """Set up `truename` and `falsename` after we know our `realname`."""
        super().__set_name__(owner, name)
        if self.truename is None:
            self.truename = self.realname
        if self.falsename is None:
            self.falsename = f"Non-{self.realname}"

    def validate(self, value: Any) -> Any:
        """Converts `value` to `True` or `False` and return it."""
        return value in (1, "1", True)

    def sortkey(self, item: Mapping) -> Any:
        """
        Returns a comparable-type version of this field's value in `item`, used
        for sorting. For `Flag` objects this is the inverse boolean of its
        value so that truthy values are ordered first.
        """
        try:
            return not self.fetch(item)
        except MissingField:
            return False

    @fieldfilter("--{optname}", is_flag=True, help="Filter on {helpname}.")
    def filter_true(self, arg: Any, value: Any, options: dict) -> bool:
        """Returns `value`. :)"""
        return value

    @fieldfilter("--non-{optname}", is_flag=True, help="Filter on non-{helpname}.")
    def filter_false(self, arg: Any, value: Any, options: dict) -> bool:
        """Returns the inversion of `value`."""
        return not self.filter_true(arg, value, options)

    def format_brief(self, value: Any, show: bool = False) -> str:
        """Returns a brief formatted version of `value` for this field."""
        return self.truename if value else self.falsename  # type: ignore

    def format_long(self, value: Any, show: bool = False) -> str:
        """
        Returns a long (single line) formatted version of `value` for this
        field.
        """
        return f"{self.realname}: {'Yes' if value else 'No'}"


class Choice(Text):
    """
    Class for defining a text field on a model. The values of this field are
    limited to a pre-defined set of values and option arguments against this
    field are automatically completed to one of the choices.
    """

    name = "CHOICE"

    def __init__(self, choices: dict[str, str] | Iterable[str], **kwargs):
        if isinstance(choices, dict):
            self.choices = {key.lower(): value or key for key, value in choices.items()}
        else:
            self.choices = {choice.lower(): choice for choice in choices}
        super().__init__(**kwargs)

    def get_metavar(self, *_):
        if self.typename:
            return self.typename
        if self.helpname:
            return self.helpname.upper()
        if self.optname:
            return self.optname.upper()
        return self.name

    def get_metavar_help(self):
        """
        Return a longer description of the option argument for this field used
        in `--help`.
        """
        return f"One of: {', '.join(sorted(set(self.choices.keys())))}."

    def preprocess_filterarg(
        self, filterarg: Any, opt: click.Parameter, options: dict
    ) -> Any:
        """
        Returns `filterarg` as-is since `Choice` field values are expected to
        exactly match the defined set of `choices`.
        """
        return filterarg

    def convert(
        self, optarg: Any, param: click.Parameter | None, ctx: click.Context | None
    ) -> Any:
        """
        Converts the option argument `optarg` to the first matching choice in
        `self.choices`. If no choice matches, then print an error message and
        exit.
        """
        optarg = optarg.lower()
        for lowerchoice, choice in self.choices.items():
            if lowerchoice.startswith(optarg):
                return choice
        self.fail(
            f"Valid choices are: {', '.join(sorted(set(self.choices.keys())))}",
            param=param,
            ctx=ctx,
        )

    @fieldfilter("--{optname}", help="Filter on matching {helpname}.")
    def filter_text(self, arg: Any, value: Any, options: dict) -> bool:
        """Return `True` if `arg` equals `value`, otherwise `False`."""
        return arg == value

    @fieldfilter("--{optname}-isnt", help="Filter on non-matching {helpname}.")
    def filter_text_isnt(self, arg: Any, value: Any, options: dict) -> bool:
        """Return `False` if `arg` equals `value`, otherwise `True`."""
        return not self.filter_text(arg, value, options)


class FieldChoice(Choice):
    """
    A `ParamType` class that completes the option argument to one of the
    `FieldBase` instances defined on the command `model`.
    """

    name = "FIELD"

    def __init__(self, fieldmap, *args, **kwargs):
        self.fieldmap = fieldmap
        super().__init__(fieldmap.keys(), *args, **kwargs)

    def convert(
        self, optarg: Any, param: click.Parameter | None, ctx: click.Context | None
    ) -> Any:
        """
        Converts the `optarg` field name to the corresponding `FieldBase`
        instance.
        """
        fieldname = super().convert(optarg, param, ctx)
        return self.fieldmap[fieldname]


class MarkupText(Text):
    """
    Class for defining a text field with HTML-like markup on a model. All
    HTML-like tags in the parsed values are replaced with ASCII styled text.
    """

    TAG_PATTERN = re.compile("<.*?>")

    def __init__(self, *args, markupstyle: dict | None = None, **kwargs):
        self.markupstyle = markupstyle or {}
        super().__init__(*args, **kwargs)

    def format_value(self, value: Any) -> str | None:
        """
        Return a string representation of `value`.

        Examples:
            >>> field = MarkupText()
            >>> field.format_value("foo")
            'foo\\x1b[0m'
            >>> field.format_value("<b>foo</b>")
            '\\x1b[1mfoo\\x1b[0m'
            >>> field.format_value("xxx<b>foo</b>yyy")
            'xxx\\x1b[0m\\x1b[1mfoo\\x1b[0myyy\\x1b[0m'
            >>> field.format_value("xxx<i>foo</i>yyy")
            'xxx\\x1b[0m\\x1b[35m\\x1b[1mfoo\\x1b[0myyy\\x1b[0m'
            >>> field.format_value("xxx<b>foo")
            'xxx\\x1b[0m\\x1b[1mfoo\\x1b[0m'
            >>> field.format_value("xxx</b>foo")
            'xxx\\x1b[0mfoo\\x1b[0m'
        """
        if value is None:
            return self.format_null()
        value = super().format_value(value)
        return "".join(part for part in self.parse_markup(value))

    @classmethod
    def strip_value(cls, value: Any) -> Any:
        """Return a version of `value` without HTML tags."""
        if isinstance(value, str):
            return cls.TAG_PATTERN.sub("", value)
        return value

    @fieldfilter("--{optname}", help="Filter on matching {helpname}.")
    def filter_text(self, arg: Any, value: Any, options: dict) -> bool:
        """
        Return `True` if `arg` equals a stripped version of `value`, otherwise
        `False`.
        """
        return super().filter_text(arg, self.strip_value(value), options)

    def parse_markup(self, value: str) -> Iterable[str]:
        """
        Parse `value` as HTML and yield ASCII styled strings. Supports only
        basic HTML and does not handle nested tags.
        """
        kwargs: dict[str, Any] = {}
        beg = 0
        while True:
            end = value.find("<", beg)
            if end >= 0:
                if beg < end:
                    yield click.style(value[beg:end], **(kwargs or self.styles or {}))
                beg = end
                end = value.index(">", beg) + 1
                tag = value[beg:end]
                if tag == "<b>":
                    kwargs["bold"] = True
                elif tag == "</b>":
                    kwargs.clear()
                elif tag == "<i>":
                    kwargs["fg"] = "magenta"
                    kwargs["bold"] = True
                elif tag == "</i>":
                    kwargs.clear()
                beg = end
            else:
                if beg < len(value):
                    yield click.style(value[beg:], **(kwargs or self.styles or {}))
                break
