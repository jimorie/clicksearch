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
    from typing import Any, Callable, IO, Iterable, Iterator, Mapping


Undefined = object()


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
            raise click.FileError(filename, "File not found")
        except PermissionError:
            raise click.FileError(filename, "Permission denied")
        except IsADirectoryError:
            raise click.FileError(filename, "Not a file")
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
        self.filterdata: dict[
            FieldBase, list[tuple[ClickSearchOption, Any]]
        ] = collections.defaultdict(list)


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
        filter_func: Callable,
        user_callback: Callable | None = None,
        **kwargs,
    ):
        kwargs["type"] = field
        super(ClickSearchOption, self).__init__(*args, **kwargs)
        self.field = field
        self.filter_func = filter_func
        self.user_callback = user_callback


class ModelBase:
    """Base class for models used to define the data items to operate on."""

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
        """Set up specific setting for the first `field`registered on this model."""
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
    def resolve_filteroptions(cls) -> Iterable[ClickSearchOption]:
        """
        Yields tuples with all `ClickSearchOption` object registered for the
        fields on this model. Searches parent classes but skips overloaded
        field names.
        """
        for field in cls.resolve_fields():
            yield from field.resolve_fieldfilteroptions()

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
        cmdobj.params.extend(cls.resolve_filteroptions())
        return cmdobj

    @classmethod
    def make_params(cls) -> Iterable[click.Parameter]:
        """Yields all standard options offered by the CLI."""
        fieldmap = {field.optname: field for field in cls.resolve_fields()}
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
            ["--inclusive"],
            is_flag=True,
            help=(
                "Use inclusive filtering that expand the result rather than "
                "shrinking it."
            ),
        )
        yield click.Option(
            ["--sort"],
            help="Sort results by given field.",
            multiple=True,
            type=FieldChoice(fieldmap),
        )
        yield click.Option(
            ["--group"],
            help="Group results by given field.",
            multiple=True,
            type=FieldChoice(fieldmap),
        )
        yield click.Option(
            ["--desc"], is_flag=True, help="Sort results in descending order."
        )
        yield click.Option(
            ["--count"],
            help="Print a breakdown of all values for given field.",
            multiple=True,
            type=FieldChoice(fieldmap),
        )

    @classmethod
    def filter_callback(
        cls, ctx: ClickSearchContext, opt: ClickSearchOption, filterarg: Any
    ) -> Any:
        """
        Registers the use of a filter option `opt` with `filterarg`. If any
        callback was registered on the option, it gets called from here.
        """
        if len(filterarg):
            if opt.user_callback:
                filterarg = opt.user_callback(ctx, opt, filterarg)
            ctx.filterdata[opt.field].append((opt, filterarg))
        return filterarg

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

        # Add on any implied filters
        cls.preprocess_implied(ctx, options)

        # Pre-process all the options
        cls.preprocess_filterdata(ctx.filterdata, options)

        # Set up an iterable over all the items
        if isinstance(ctx.command, ClickSearchCommand):
            items = ctx.command.reader(options)

        # Filter the items
        items = cls.filter_items(ctx, items, options)

        # Sort the items
        items = cls.sort_items(items, options)

        # Adjust verbose based on numer of items found
        items = cls.adjust_verbose(items, options)

        # Set print_func based on verbosity
        if options["verbose"] < 0:
            print_func = None
        elif options["verbose"] and not options["brief"]:
            print_func = cls.print_long
        else:
            print_func = cls.print_brief

        # Set up info for print group headers
        current_group: list[Any] | None = None
        group_fields: Iterable[FieldBase] | None = None
        if options["group"]:
            group_fields = options["group"]
            current_group = []

        # Collect the fields we are interested in printing
        if options["show"] and cls._fields[cls]:
            title_field, *_ = cls._fields[cls].values()
            if title_field in options["show"]:
                show_fields = options["show"]
            else:
                show_fields = [title_field, *options["show"]]
        else:
            show_fields = list(cls.collect_visible_fields(options))

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
                    if current_group and not options["verbose"]:
                        click.echo()
                    header = " | ".join(
                        field.format_brief(value)
                        for field, value in zip(group_fields, next_group)
                    )
                    click.secho(f"[ {header} ]", fg="yellow", bold=True)
                    click.echo()
                    current_group = next_group

            # Print the item
            print_func(show_fields, item, options)

        # Print breakdown counts
        if options["verbose"] == 0:
            click.echo()
        cls.print_counts(counts, item_count)

    @classmethod
    def preprocess_filterdata(cls, filterdata: dict, options: dict):
        """
        Pre-processes data in `filterdata` after we have received all options.
        Actual pre-processing is delegated to `FieldBase.preprocess_filterarg`.
        """
        for field, fieldfilters in filterdata.items():
            for i, (opt, filterargs) in enumerate(fieldfilters):
                fieldfilters[i] = (
                    opt,
                    tuple(
                        field.preprocess_filterarg(filterarg, opt, options)
                        for filterarg in filterargs
                    ),
                )

    @classmethod
    def preprocess_implied(cls, ctx: ClickSearchContext, options: dict):
        """Add all "implied" filters for referenced fields to the filterdata."""
        fields = set(ctx.filterdata)
        fields.update(options["count"])
        fields.update(options["sort"])
        fields.update(options["group"])
        fields.update(options["show"])
        for field in fields:
            if field.implied:
                parsed, _, params = ctx.command.parser.parse_args(  # type: ignore
                    shlex.split(field.implied)
                )
                for paramname, values in parsed.items():
                    for param in params:
                        if param.name == paramname:
                            break
                    else:
                        continue
                    if param.field not in ctx.filterdata:
                        ctx.filterdata[param.field] = [
                            (
                                param,
                                tuple(
                                    param.field.convert(value, param, ctx)
                                    for value in values
                                ),
                            )
                        ]

    @classmethod
    def filter_items(
        cls, ctx: ClickSearchContext, items: Iterable[Mapping], options: dict
    ) -> Iterable[Mapping]:
        """Yields the items that pass `cls.test_item`."""
        for item in items:
            if cls.test_item(ctx, item, options):
                yield item

    @classmethod
    def test_item(cls, ctx: ClickSearchContext, item: Mapping, options: dict) -> bool:
        """
        Returns `True` if `item` passes all filter options used, otherwise
        `False`.
        """
        for field, fieldfilters in ctx.filterdata.items():
            try:
                value = field.fetch(item)
            except MissingField:
                return False
            any_or_all = any if field.inclusive or options["inclusive"] else all
            if not any_or_all(
                any_or_all(
                    opt.filter_func(opt.field, filterarg, value, options)
                    for filterarg in filterargs
                )
                for opt, filterargs in fieldfilters
            ):
                return False
        return True

    @classmethod
    def sort_items(cls, items: Iterable[Mapping], options: dict) -> Iterable[Mapping]:
        """Returns `items` sorted according to the --group and --sort `options`."""
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
        for field in cls.resolve_fields():
            if options["verbose"] < field.verbosity:
                continue
            yield field

    @classmethod
    def print_brief(cls, fields: list[FieldBase], item: Mapping, options: dict):
        """Prints a one-line representation of `item`."""
        first = True
        for field in fields:
            try:
                value = field.fetch(item)
            except MissingField:
                continue
            value = field.format_brief(value)
            if value:
                if first:
                    if len(fields) > 1:
                        if field.styles:
                            value += click.style(": ", **field.styles)
                        else:
                            value += ": "
                    first = False
                else:
                    value += ". "
                click.echo(value, nl=False)
        click.echo()

    @classmethod
    def print_long(cls, fields: list[FieldBase], item: Mapping, options: dict):
        """Prints a multi-line representation of `item`."""
        for field in fields:
            try:
                value = field.fetch(item)
            except MissingField:
                continue
            value = field.format_long(value)
            if value:
                click.echo(value)
        click.echo()

    @classmethod
    def print_counts(cls, counts: dict[FieldBase, dict[str, int]], item_count: int):
        """Prints `counts` breakdowns."""
        for field, breakdown in counts.items():
            click.secho(f"[ {field.realname} counts ]", fg="green", bold=True)
            click.echo()
            for value, count in sorted(
                breakdown.items(), key=operator.itemgetter(1), reverse=True
            ):
                click.echo(click.style(f"{value}: ", bold=True) + str(count))
            click.echo()
        click.echo(
            click.style("Total count: ", fg="green", bold=True) + str(item_count)
        )


def fieldfilter(*param_decls, **opt_kwargs):
    """
    Decorator to mark a `FieldBase` class method as a field filter.
    Type signature matches the `click.option` decorator.
    """

    class decorator:
        def __init__(self, func: Callable):
            self.func = func
            self.opt_kwargs = {"param_decls": param_decls, **opt_kwargs}
            if "help" not in self.opt_kwargs and func.__doc__:
                self.opt_kwargs["help"] = inspect.cleandoc(func.__doc__)

        def __set_name__(self, owner: type[FieldBase], name: str):
            owner.register_filter(self.func, self.opt_kwargs)
            setattr(owner, name, self.func)

    return decorator


class FieldBase(click.ParamType):
    """
    Base class for the properties that define the fields on `ModelBase`
    classes.
    """

    name: str

    fieldfilters: dict[
        type[FieldBase], list[tuple[Callable, dict]]
    ] = collections.defaultdict(list)

    def __init__(
        self,
        default: Any | type = MissingField,
        inclusive: bool = False,
        skip_filters: Iterable[Callable] | None = None,
        keyname: str | None = None,
        optname: str | None = None,
        realname: str | None = None,
        helpname: str | None = None,
        typename: str | None = None,
        verbosity: int = 0,
        unlabeled: bool | object = Undefined,
        brief_format: str | None = None,
        implied: str | None = None,
        styles: dict | None = None,
    ):
        self.default = default
        self.inclusive = inclusive
        self.skip_filters = skip_filters
        self.keyname = keyname
        self.optname = optname
        self.realname = realname
        self.helpname = helpname
        self.typename = typename
        self.verbosity = verbosity
        self.unlabeled = unlabeled
        self.brief_format = brief_format
        self.implied = implied
        self.styles = styles

        # Set when assigned to a model
        self.owner: type[ModelBase] = None  # type: ignore

    def __set_name__(self, owner: type[ModelBase], name: str):
        """
        Registers this `FieldBase` instance on a `ModelBase` class under the
        given `name`.
        """
        self.owner = owner
        if self.keyname is None:
            self.keyname = name
        if self.realname is None:
            self.realname = name.replace("_", " ").title()
        if self.helpname is None:
            self.helpname = self.realname.lower()
        if self.optname is None:
            self.optname = self.realname.lower().replace(" ", "-")
        owner.register_field(name, self)

    @classmethod
    def register_filter(cls, filter_func: Callable, opt_kwargs: dict):
        """
        Registers a `filter_func` with `Option` kwargs `opt_kwargs`. Called by
        the `fieldfilter` decorator.
        """
        cls.fieldfilters[cls].append((filter_func, opt_kwargs))

    def resolve_fieldfilters(self) -> Iterable[tuple[Callable, dict]]:
        """
        Yields all filters defined with the `fieldfilter` decorator on this
        field and its ancestors. Overloaded filters are only yielded once.
        """
        seen = set()
        for ancestor in self.__class__.__mro__:
            if not issubclass(ancestor, FieldBase):
                break
            for filter_func, opt_kwargs in self.fieldfilters[ancestor]:
                if self.skip_filters and filter_func in self.skip_filters:
                    continue
                if filter_func.__name__ in seen:
                    continue
                yield filter_func, opt_kwargs
                seen.add(filter_func.__name__)

    def resolve_fieldfilteroptions(self) -> Iterable[ClickSearchOption]:
        """
        Yields `ClickSearchOption` objects for all filters defined with the
        `fieldfilter` decorator on this field and its ancestors. Overloaded
        filters are only yielded once.
        """
        if not self.owner:
            raise RuntimeError("cannot resolve filter options without owner set")
        for filter_func, opt_kwargs in self.resolve_fieldfilters():
            new_kwargs = opt_kwargs.copy()
            new_kwargs = self.format_opt_kwargs(new_kwargs)
            callback = new_kwargs.pop("callback", None)
            yield self.owner._option_cls(
                filter_func=filter_func,
                user_callback=callback,
                callback=self.owner.filter_callback,
                field=self,
                multiple=True,
                **new_kwargs,
            )

    def format_opt_kwargs(self, opt_kwargs: dict) -> dict:
        """Resolves format placeholders in all `opt_kwargs`."""
        if "param_decls" in opt_kwargs:
            opt_kwargs["param_decls"] = [
                self.format_opt_arg(arg) for arg in opt_kwargs["param_decls"]
            ]
        if "help" in opt_kwargs:
            opt_kwargs["help"] = self.format_opt_arg(opt_kwargs["help"])
        return opt_kwargs

    def format_opt_arg(self, arg: str) -> str:
        """Resolves format placeholders in the single `arg`."""
        return arg.format(optname=self.optname, helpname=self.helpname)

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
        except KeyError:
            if default is MissingField:
                if self.default is MissingField:
                    raise MissingField(f"Value missing: {self.keyname}")
                else:
                    value = self.default
            else:
                value = default
        return self.validate(value)

    def sortkey(self, item: Mapping) -> Any:
        """
        Returns a comparable-type version of this field's value in `item`,
        used for sorting.
        """
        return self.fetch(item)

    def format_value(self, value: Any) -> str:
        """Return a string representation of `value`."""
        if value is None or value == "":
            return ""
        return self.style(str(value))

    def format_brief(self, value: Any) -> str:
        """Return a brief formatted version of `value` for this field."""
        value = self.format_value(value)
        if self.brief_format:
            value = self.brief_format.format(name=self.realname, value=value)
        return value

    def format_long(self, value: Any) -> str:
        """
        Returns a long (single line) formatted version of `value` for this
        field.
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
            counts[self.format_brief(self.fetch(item))] += 1
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
            brief_format = '{name} {value}'
        super().__init__(*args, brief_format=brief_format, unlabeled=unlabeled, **kwargs)
        self.specials = specials

    def get_metavar_help(self):
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

        def compare(x):
            try:
                return op(x, filterarg)
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
        if value is None or value == '':
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

    def format_brief(self, value: Any) -> str:
        """Returns a brief formatted version of `value` for this field."""
        if value is None:
            return f"No {self.realname}"
        return super().format_brief(value)


class Text(FieldBase):
    """Class for defining a text field on a model."""

    name = "TEXT"

    def get_metavar_help(self):
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
        if not options["case"]:
            filterarg = filterarg.lower()
        if options["regex"]:
            if options["exact"]:
                filterarg = f"^{filterarg}$"
            try:
                filterarg = re.compile(filterarg)
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
        if not options["case"]:
            value = value.lower()
        if options["regex"]:
            return bool(arg.search(value))
        if arg.startswith("!"):
            negate = not arg.startswith("!!")
            arg = arg[1:]
        else:
            negate = False
        if options["exact"]:
            result = value and arg == value
        else:
            result = value and arg in value
        return result ^ negate


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
        return any(
            super(DelimitedText, self).filter_text(arg, part, options)
            for part in self.parts(value)
        )


class Flag(FieldBase):
    """Class for defining a boolean field on a model."""

    name = "FLAG"

    def __init__(self, truename: str | None = None, falsename: str | None = None, **kwargs):
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
        return not self.fetch(item)

    @fieldfilter("--{optname}", is_flag=True, help="Filter on {helpname}.")
    def filter_true(self, arg: Any, value: Any, options: dict) -> bool:
        """Returns `value`. :)"""
        return value

    @fieldfilter("--non-{optname}", is_flag=True, help="Filter on non-{helpname}.")
    def filter_false(self, arg: Any, value: Any, options: dict) -> bool:
        """Returns the inversion of `value`."""
        return not self.filter_true(arg, value, options)

    def format_brief(self, value: Any) -> str:
        """Returns a brief formatted version of `value` for this field."""
        return self.truename if value else self.falsename

    def format_long(self, value: Any) -> str:
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
        return f"One of: {', '.join(sorted(set(self.choices.values())))}."

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
            f"Valid choices are: {', '.join(sorted(set(self.choices.values())))}",
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
        return arg != value


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
