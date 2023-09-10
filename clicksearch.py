from __future__ import annotations

import collections
import itertools
import json
import operator
import re
import typing

import click


if typing.TYPE_CHECKING:
    from typing import Any, Callable, IO, Iterable, Mapping


class ClickSearchException(click.ClickException):
    """Base clicksearch excepton class."""

    pass


class MissingField(ClickSearchException):
    """
    Exception raised when a `FieldBase` instance cannot find its value in a
    data set.
    """

    pass


class ReaderBase:
    """Base class for reader objects."""

    def read(self, options: dict) -> Iterable[Mapping]:
        raise NotImplementedError


class FileReader(ReaderBase):
    """Base class for reader objects operating on files."""

    @staticmethod
    def filenames(options: dict) -> Iterable[str]:
        """Returns the filenames in `options`."""
        return options.get("file", [])

    def files(self, options: dict) -> Iterable[IO]:
        """
        Yields file handles for the file names in `self.filenames`. Raises
        variants of `OSError` if a file name cannot be opened for reading.
        """
        try:
            for filename in self.filenames(options):
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

    def read(self, options: dict) -> Iterable[Mapping]:
        """Yields items from files in `self.files`."""
        for fd in self.files(options):
            doc = json.load(fd)
            for item in doc:
                yield item


class JsonLineReader(FileReader):
    """
    Reader class that reads items from files where every line is a JSON
    object.
    """

    def read(self, options: dict) -> Iterable[Mapping]:
        """Yields items from files in `self.files`."""
        for fd in self.files(options):
            for line in fd:
                yield json.loads(line.rstrip())


class ClickSearchCommand(click.Command):
    """
    Default clicksearch `Command` class. Holds a reference to the `ModelBase`
    class that defines the data items to operate on.
    """

    def __init__(self, *args, model: type[ModelBase], **kwargs):
        super().__init__(*args, **kwargs)
        self.model = model


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


class ClickSearchChoice(click.ParamType):
    """
    A `ParamType` class that completes the option argument to the first match
    in a given set of choices.
    """

    name = "CHOICE"

    def __init__(self, choices: dict[str, str] | Iterable[str]):
        if isinstance(choices, dict):
            self.choices = {key.lower(): value or key for key, value in choices.items()}
        else:
            self.choices = {choice.lower(): choice for choice in choices}

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


class ClickSearchField(ClickSearchChoice):
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


class ModelBase:
    """Base class for models used to define the data items to operate on."""

    __cmd_name__: str

    command_cls = ClickSearchCommand
    option_cls = ClickSearchOption
    argument_cls = click.Argument
    reader_cls = JsonLineReader
    fields: dict[FieldBase, list[ClickSearchOption]] = collections.defaultdict(list)
    filterdata: dict[
        FieldBase, list[tuple[ClickSearchOption, Any]]
    ] = collections.defaultdict(list)

    @classmethod
    def make_command(cls) -> click.Command:
        """Returns the `click.Command` object used to run the CLI."""
        cmdobj = cls.command_cls(cls.__cmd_name__, callback=cls.main, model=cls)
        cmdobj.params.append(cls.make_argument())
        cmdobj.params.extend(cls.make_options())
        for field, options in cls.fields.items():
            cmdobj.params.extend(options)
        return cmdobj

    @classmethod
    def make_options(cls) -> Iterable[click.Option]:
        """Yields all standard options offered by the CLI."""
        fieldmap = {field.optname: field for field in cls.fields}
        yield click.Option(["--verbose", "-v"], count=True, help="Show more data.")
        yield click.Option(
            ["--brief"],
            count=True,
            help="Show one line of data, regardless the level of verbose.",
        )
        yield click.Option(
            ["--case"], is_flag=True, help="Use case sensitive filtering."
        )
        yield click.Option(["--exact"], is_flag=True, help="Use exact match filtering.")
        yield click.Option(
            ["--regex"], is_flag=True, help="Use regular rexpressions when filtering."
        )
        yield click.Option(
            ["--inclusive"], is_flag=True, help="Use regular rexpressions when filtering."
        )
        yield click.Option(
            ["--sort"],
            help="Sort results by given field.",
            multiple=True,
            type=ClickSearchField(fieldmap),
        )
        yield click.Option(
            ["--group"],
            help="Group results by given field.",
            multiple=True,
            type=ClickSearchField(fieldmap),
        )
        yield click.Option(
            ["--desc"], is_flag=True, help="Sort results in descending order."
        )
        yield click.Option(
            ["--count"],
            help="Print a breakdown of all values for given field.",
            multiple=True,
            type=ClickSearchField(fieldmap),
        )

    @classmethod
    def make_argument(cls) -> click.Argument:
        """Returns the `click.Argument` object used to handle non-option parameters."""
        return cls.argument_cls(["file"], nargs=-1)

    @classmethod
    def filter_callback(
        cls, ctx: click.Context, opt: ClickSearchOption, filterarg: Any
    ) -> Any:
        """
        Registers the use of a filter option `opt` with `filterarg`. If any
        callback was registered on the option, it gets called from here.
        """
        if len(filterarg):
            if opt.user_callback:
                filterarg = opt.user_callback(ctx, opt, filterarg)
            cls.filterdata[opt.field].append((opt, filterarg))
        return filterarg

    @classmethod
    def register_field(cls, field: FieldBase):
        """
        Registers a `field` assigned to this `cls` and all the options defined
        for `field`.
        """
        fieldoptions = cls.fields[field]
        for filter_func, opt_kwargs in field.resolve_fieldfilters():
            new_kwargs = opt_kwargs.copy()
            new_kwargs = field.format_opt_kwargs(new_kwargs)
            callback = new_kwargs.pop("callback", None)
            fieldoptions.append(
                cls.option_cls(
                    filter_func=filter_func,
                    user_callback=callback,
                    callback=cls.filter_callback,
                    field=field,
                    multiple=True,
                    **new_kwargs,
                )
            )

    @classmethod
    def cli(cls):
        """Run the CLI."""
        cls.make_command()()

    @classmethod
    def main(cls, **options: Any):
        """Main program flow used by the CLI."""

        # Pre-process all the options
        cls.preprocess_filterdata(options)

        # Set up an iterable over all the items
        reader = cls.reader_cls()
        items = reader.read(options)

        # Filter the items
        items = cls.filter_items(items, options)

        # Sort the items
        items = cls.sort_items(items, options)

        # Adjust verbose based on numer of items found
        items = cls.adjust_verbose(items, options)
        verbose = options["verbose"]

        # Set print_func based on verbosity
        if verbose < 0:
            print_func = None
        elif verbose and not options["brief"]:
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
        print_fields = list(cls.collect_visible_fields(options))

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
                    if current_group and not verbose:
                        click.echo()
                    header = " | ".join(
                        field.format_brief(value)
                        for field, value in zip(group_fields, next_group)
                    )
                    click.secho(f"[ {header} ]", fg="yellow", bold=True)
                    click.echo()
                    current_group = next_group

            # Print the item
            print_func(print_fields, item, options)

        # Print breakdown counts
        if verbose >= 0:
            click.echo()
        cls.print_counts(counts, item_count)

    @classmethod
    def preprocess_filterdata(cls, options: dict):
        """
        Pre-processes data in `cls.filterdata` after we have received all
        options. Actual pre-processing is delegated to
        `FieldBase.preprocess_filterarg`.
        """
        for field, fieldfilters in cls.filterdata.items():
            for i, (opt, filterargs) in enumerate(fieldfilters):
                fieldfilters[i] = (
                    opt,
                    tuple(
                        field.preprocess_filterarg(filterarg, opt, options)
                        for filterarg in filterargs
                    )
                )

    @classmethod
    def filter_items(cls, items: Iterable[Mapping], options: dict) -> Iterable[Mapping]:
        """Yields the items that pass `cls.test_item`."""
        for item in items:
            if cls.test_item(item, options):
                yield item

    @classmethod
    def test_item(cls, item: Mapping, options: dict) -> bool:
        """
        Returns `True` if `item` passes all filter options used, otherwise
        `False`.
        """
        for field, fieldfilters in cls.filterdata.items():
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
        elif isinstance(items, list):
            if len(items) == 1:
                options["verbose"] += 1
        elif not options["count"]:
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
        for field in cls.fields:
            if options["verbose"] < field.verbosity:
                continue
            yield field

    @classmethod
    def print_brief(cls, fields: Iterable[FieldBase], item: Mapping, options: dict):
        """Prints a one-line representation of `item`."""
        first = True
        for field in fields:
            try:
                value = field.fetch(item)
            except MissingField:
                continue
            value = field.format_brief(value)
            if first:
                value += click.style(": ", fg=field.fg, bold=field.bold)
                first = False
            else:
                value += ". "
            click.echo(value, nl=False)
        click.echo()

    @classmethod
    def print_long(cls, fields: list[FieldBase], item: Mapping, options: dict):
        """Prints a multi-line representation of `item`."""
        first = True
        for field in fields:
            try:
                value = field.fetch(item)
            except MissingField:
                continue
            if value in (None, ""):
                continue
            if first:
                value = click.style(value, fg="cyan", bold=True)
                first = False
            else:
                value = field.format_long(value)
            click.echo(value)
        click.echo()

    @classmethod
    def print_counts(cls, counts: dict[FieldBase, dict[str, int]], item_count: int):
        """Prints `counts` breakdowns."""
        for field, breakdown in counts.items():
            click.secho(f"[ {field.fmtname} counts ]", fg="green", bold=True)
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

    fieldfilters: dict[type, list[tuple[Callable, dict]]] = collections.defaultdict(
        list
    )

    def __init__(
        self,
        default: Any = None,
        nullable: bool = False,
        inclusive: bool = False,
        key: str | None = None,
        optname: str | None = None,
        helpname: str | None = None,
        typename: str | None = None,
        fmtname: str | None = None,
        verbosity: int = 0,
        standalone: bool = False,
        fg: str | None = None,
        bold: bool = False,
    ):
        self.default = default
        self.nullable = nullable
        self.inclusive = inclusive
        self.key = key
        self.optname = optname
        self.helpname = helpname
        self.fmtname = fmtname
        self.verbosity = verbosity
        self.standalone = standalone
        self.fg = fg
        self.bold = bold
        if typename:  # Otherwise fallback on class variable
            self.name = typename

    def __set_name__(self, owner: type[ModelBase], name: str):
        """
        Registers this `FieldBase` instance on a `ModelBase` class under the
        given `name`.
        """
        if self.key is None:
            self.key = name
        if self.optname is None:
            self.optname = name
        if self.helpname is None:
            self.helpname = name
        if self.fmtname is None:
            self.fmtname = name.title()
        owner.register_field(self)

    @classmethod
    def register_filter(cls, filter_func: Callable, opt_kwargs: dict):
        """
        Registers a `filter_func` with `Option` kwargs `opt_kwargs`. Called by
        the `fieldfilter` decorator.
        """
        cls.fieldfilters[cls].append((filter_func, opt_kwargs))

    @classmethod
    def resolve_fieldfilters(cls) -> Iterable[tuple[Callable, dict]]:
        """
        Yields all filters defined with the `fieldfilter` decorator on `cls`
        and its ancestors. Overloaded filters are only yielded once.
        """
        seen = set()
        for ancestor in cls.__mro__:
            if not issubclass(ancestor, FieldBase):
                break
            for filter_func, opt_kwargs in cls.fieldfilters[ancestor]:
                if filter_func.__name__ not in seen:
                    yield filter_func, opt_kwargs
                seen.add(filter_func.__name__)

    def convert(
        self, filterarg: Any, param: click.Parameter | None, ctx: click.Context | None
    ) -> Any:
        """
        Converts an option argument `optarg` for this field and return the new
        value. This calls `validate` and handles any `TypeError` or
        `ValueError` raised by re-raising a `click.BadParameter` exception.
        """
        try:
            return self.validate(filterarg)
        except (ValueError, TypeError):
            raise click.BadParameter(str(filterarg), ctx=ctx, param=param)

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
            value = item[self.key]
        except KeyError:
            if default is MissingField:
                raise MissingField(f"Value missing: {self.key}")
            value = default
        if value is None and self.nullable is False:
            if default is MissingField:
                raise MissingField(f"Value required: {self.key}")
            value = default
        return self.validate(value)

    def sortkey(self, item: Mapping) -> Any:
        """
        Returns a comparable-type version of this field's value in `item`,
        used for sorting.
        """
        return self.fetch(item)

    def format_brief(self, value: Any) -> str:
        """Return a brief formatted version of `value` for this field."""
        return self.style(value)

    def format_long(self, value: Any) -> str:
        """
        Returns a long (single line) formatted version of `value` for this
        field.
        """
        value = self.style(value)
        if self.standalone:
            return value
        return f"{self.fmtname}: {value}"

    def style(self, value: Any) -> str:
        """Returns a styled `value` for this field."""
        if self.fg:
            return click.style(value, fg=self.fg, bold=self.bold)
        return value

    def count(self, item: Mapping, counts: collections.Counter):
        """Increments the `counts` count of this field's value in `item` by 1."""
        try:
            counts[self.format_brief(self.fetch(item))] += 1
        except MissingField:
            pass


class Number(FieldBase):
    """Class for defining a numeric field on a model."""

    name = "NUMBER"
    operators = [
        ("==", operator.eq),
        ("!=", operator.ne),
        ("!", operator.ne),
        ("<=", operator.le),
        ("<", operator.lt),
        (">=", operator.ge),
        (">", operator.gt),
    ]

    def __init__(self, *args, specials: list[str] | None, **kwargs):
        super().__init__(*args, **kwargs)
        self.specials = specials

    def convert(
        self, filterarg: Any, param: click.Parameter | None, ctx: click.Context | None
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
        if value is None:
            return None
        if self.specials and value in self.specials:
            return value
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
            return f"No {self.fmtname}"
        return f"{value} {self.fmtname}"


class String(FieldBase):
    """Class for defining a text field on a model."""

    name = "TEXT"

    def preprocess_filterarg(
        self, filterarg: Any, opt: click.Parameter, options: dict
    ) -> Any | re.Pattern:
        """
        Pre-processes `filterarg` for comparison against `String` field
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
        for sorting. For `String` objects this is guaranteed to be of type
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
        if options["exact"]:
            return arg and value and arg == value
        return value and arg in value

    @fieldfilter("--{optname}-isnt", help="Filter on non-matching {helpname}")
    def filter_text_isnt(self, arg: Any, value: Any, options: dict) -> bool:
        """
        Returns `False` if `arg` matches `value`, depending on `options`,
        otherwise `True`.
        """
        return not self.filter_text(self, arg, value, options)


class Flag(FieldBase):
    """Class for defining a boolean field on a model."""

    name = "FLAG"

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
        return str(self.fmtname) if value else f"Non-{self.fmtname}"

    def format_long(self, value: Any) -> str:
        """
        Returns a long (single line) formatted version of `value` for this
        field.
        """
        return f"{self.fmtname}: {'Yes' if value else 'No'}"


class Choice(String, ClickSearchChoice):
    """
    Class for defining a text field on a model. The values of this field are
    limited to a pre-defined set of values and option arguments against this
    field are automatically completed to one of the choices.
    """

    name = "CHOICE"

    def __init__(
        self,
        choices: dict[str, str] | Iterable[str],
        **kwargs,
    ):
        String.__init__(self, **kwargs)
        ClickSearchChoice.__init__(self, choices)

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
        Converts the option argument `optarg` using the
        `ClickSearchChoice.convert` method.
        """
        return ClickSearchChoice.convert(self, optarg, param, ctx)

    @fieldfilter("--{optname}", help="Filter on matching {helpname}.")
    def filter_text(self, arg: Any, value: Any, options: dict) -> bool:
        """Return `True` if `arg` equals `value`, otherwise `False`."""
        return arg == value


class SeparatedString(String):
    """
    Class for defining a multi-value text field on a model. The values of this
    field can include a given string separator, so that when split by this
    separator each split part is treated individually.
    """

    def __init__(self, separator: str = ",", **kwargs):
        super().__init__(**kwargs)
        self.separator = separator

    def parts(self, value: str) -> Iterable[str]:
        """Yields each individual part of the `SeparatedString`."""
        for part in value.split(self.separator):
            part = part.strip()
            if part:
                yield part

    def count(self, item: Mapping, counts: collections.Counter):
        """
        Increments the count of each part in the `SeparatedString`
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
            super(SeparatedString, self).filter_text(arg, part, options)
            for part in self.parts(value)
        )


class Test(ModelBase):
    __cmd_name__ = "Test"
    name = String(standalone=True, fg="cyan", bold=True)
    descriptor = String(verbosity=1, standalone=True, fg="yellow")
    subtypes = SeparatedString(
        optname="subtype", separator=".", verbosity=1, standalone=True, fg="magenta"
    )
    unique = Flag(helpname="uniqueness")
    faction = Choice(
        choices={
            "Agency": "The Agency",
            "Cthulhu": None,
            "Hastur": None,
            "Miskatonic University": None,
            "Neutral": None,
            "Shub-Niggurath": None,
            "Silver Twilight": None,
            "Syndicate": None,
            "The Agency": None,
            "Yog-Sothoth": None,
        },
        inclusive=True,
    )
    cardtype = Choice(
        choices=["Character", "Event", "Story", "Support"],
        key="type",
        helpname="card type",
        typename="CARD TYPE",
        optname="type",
        inclusive=True,
    )
    cost = Number(specials=["X"])
    restricted = Flag(verbosity=2)
    banned = Flag(verbosity=2)


if __name__ == "__main__":
    Test.cli()
