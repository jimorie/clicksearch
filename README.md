# Clicksearch

Clicksearch is a framework for writing CLI programs that filter a stream of data objects. Clicksearch lets you define a model of the objects your program should work with, and based on this model Clicksearch creates a CLI with options for filtering on the defined fields.

Clicksearch is based on the [Click](https://click.palletsprojects.com) framework, which handles all of the heavy lifting CLI work.

## The Basics

Let's start with a basic example on how to write a simple Clicksearch program.

### The Model

At the heart of Clicksearch is the model. Every Clicksearch program needs to define a subclass of the `ModelBase` class, that describes the supported data:

```python
class MyModel(ModelBase):
    name = Text()
    value = Number()
```

From this simple model you can launch your CLI program by calling the `ModelBase.cli` class method:

```pycon
>>> MyModel.cli('--help')
Usage: doctest.py [OPTIONS] [FILE]...

Options:
  -v, --verbose  Show more data.
  --brief        Show one line of data, regardless the level of verbose.
  --long         Show multiple lines of data, regardless the level of verbose.
  --show FIELD   Show given field only. Can be repeated to show multiple
                 fields in given order.
  --case         Use case sensitive filtering.
  --exact        Use exact match filtering.
  --regex        Use regular rexpressions when filtering.
  --inclusive    Use inclusive filtering that expand the result rather than
                 shrinking it.
  --sort FIELD   Sort results by given field.
  --group FIELD  Group results by given field.
  --desc         Sort results in descending order.
  --count FIELD  Print a breakdown of all values for given field.
  --help         Show this message and exit.

Field filters:
  --name TEXT     Filter on matching name.
  --value NUMBER  Filter on matching value (number comparison).

Where:
  FIELD   One of: name, value.
  NUMBER  A number optionally prefixed by one of the supported comparison
          operators: ==, =, !=, !, <=, <, >=, >. With == being the default if
          only a number is given.
  TEXT    A text partially matching the field value. The --case, --regex and
          --exact options can be applied. If prefixed with ! the match is
          negated.
```

> :exclamation: The first argument to `MyModel.cli` is the command line arguments as a string. This is optional and generally not required when launching the program from a terminal, but here we need it since we are launching from the Python REPL.

We can see from the `--help` output that we have a bunch of basic options, that will be the same for all Clicksearch programs, and then we have a a few options called *field filters*, that are based on the fields defined on the model.

### The Reader

The next thing Clicksearch needs is a data source, called a _reader_. In Python terms the reader should be a `Callable[[Mapping], Iterable[Mapping]]` object. That is: it should be a callable object that takes a single `dict` argument (the parsed [Click](https://click.palletsprojects.com) parameters) and returns some sort of object that can be iterated over to generate the data objects that Clicksearch should work with.

In its simplest form this can be a function that return, for instance, a `list`:

```python
def reader(options: dict):
    return [
        {'name': 'Lorem Ipsum', 'value': 1},
        {'name': 'Dolor Sit Amet', 'value': 2},
    ]
```

Or perhaps be a Python generator:

```python
def reader(options: dict):
    yield {'name': 'Lorem Ipsum', 'value': 1}
    yield {'name': 'Dolor Sit Amet', 'value': 2, 'foo': 42}
```

Provide the reader to `MyModel.cli` with the `reader` keyword argument. Now you are ready to start using the CLI program! Pass in the command line options as the first argument to `MyModel.cli`:

```pycon
>>> MyModel.cli('', reader=reader)
Lorem Ipsum: 1 Value.
Dolor Sit Amet: 2 Value.

Total count: 2
```

```pycon
>>> MyModel.cli('--verbose', reader=reader)
Lorem Ipsum
Value: 1

Dolor Sit Amet
Value: 2

Total count: 2
```

```pycon
>>> MyModel.cli('--value 2', reader=reader)
Dolor Sit Amet
Value: 2

Total count: 1
```

### The Script

Your complete CLI program would then look something like this:

[DOCTEST_BREAK]::

```python
#!/usr/bin/env python3

from clicksearch import ModelBase, Text, Number

class MyModel(ModelBase):
    name = Text()
    value = Number()

def reader(options: dict):
    yield {'name': 'Lorem Ipsum', 'value': 1}
    yield {'name': 'Dolor Sit Amet', 'value': 2}

if __name__ == '__main__':
    MyModel.cli(reader=reader)
```

[DOCTEST_CONTINUE]::

## Fields

Fields are the objects used to compose your model. Clicksearch comes with number of basic field types built-in, but you can of course also define your own field type by subclassing from the `FieldBase` class (or from any other built-in field type).

### Text

`Text` fields support `str` values and implement a single filter option that matches any part of the field value. In the example below the option will be given the default name `--name`. The behavior of the `Text` field filter can then be further controlled with the `--case`, `--exact` and `--regex` options.

```python
class MyTextModel(ModelBase):
    name = Text()
```

```pycon
>>> MyTextModel.cli('', reader=reader)
Lorem Ipsum
Dolor Sit Amet

Total count: 2
```

```pycon
>>> MyTextModel.cli('--name "lorem"', reader=reader)
Lorem Ipsum

Total count: 1
```

```pycon
>>> MyTextModel.cli('--name "amet"', reader=reader)
Dolor Sit Amet

Total count: 1
```

```pycon
>>> MyTextModel.cli('--name "foo"', reader=reader)

Total count: 0
```

#### `--case`

The `--case` option makes the `Text` field filter case sensitive.

```pycon
>>> MyTextModel.cli('--name "lorem" --case', reader=reader)

Total count: 0
```

```pycon
>>> MyTextModel.cli('--name "Lorem" --case', reader=reader)
Lorem Ipsum

Total count: 1
```

#### `--exact`

The `--exact` option makes the `Text` field filter require a full match.

```pycon
>>> MyTextModel.cli('--name "Lorem" --exact', reader=reader)

Total count: 0
```

```pycon
>>> MyTextModel.cli('--name "Lorem Ipsum" --exact', reader=reader)
Lorem Ipsum

Total count: 1
```

#### `--regex`

The `--regex` option makes the `Text` field filter operate as a [regular expression](https://docs.python.org/3/library/re.html).

```pycon
>>> MyTextModel.cli('--name "\\b[lorem]+\\b" --regex', reader=reader)
Lorem Ipsum

Total count: 1
```

```pycon
>>> MyTextModel.cli('--name "\\b[loremd]+\\b" --regex', reader=reader)
Lorem Ipsum
Dolor Sit Amet

Total count: 2
```

```pycon
>>> MyTextModel.cli('--name "b]d r[g}x" --regex', reader=reader)
Usage: ...

Error: Invalid value for '--name': Invalid regular expression
```

### Number

`Number` fields support numeric values and implement a single filter that allows basic comparisons with the field value. In the example below the option will be given the default name `--value`. The supported comparison operators are: `==` (the default), `!=`, `<`, `<=`, `>` and `>=`.

```python
class MyNumberModel(ModelBase):
    name = Text()
    value = Number()
```

```pycon
>>> MyNumberModel.cli('', reader=reader)
Lorem Ipsum: 1 Value.
Dolor Sit Amet: 2 Value.

Total count: 2
```

```pycon
>>> MyNumberModel.cli('--value 1', reader=reader)
Lorem Ipsum
Value: 1

Total count: 1
```

```pycon
>>> MyNumberModel.cli('--value ">0"', reader=reader)
Lorem Ipsum: 1 Value.
Dolor Sit Amet: 2 Value.

Total count: 2
```

```pycon
>>> MyNumberModel.cli('--value ">1"', reader=reader)
Dolor Sit Amet
Value: 2

Total count: 1
```

```pycon
>>> MyNumberModel.cli('--value "X"', reader=reader)
Usage: ...

Error: Invalid value for '--value': X
```

#### Specials

`Number` fields can also be configured to accept non-numeric values with the `specials` parameter. Such special values only support direct equality comparison.

```python
class MyNumberModel(ModelBase):
    name = Text()
    value = Number(specials=['X'])

def specials(options: dict):
    yield {'name': 'Lorem Ipsum', 'value': 1}
    yield {'name': 'Dolor Sit Amet', 'value': 'X'}
```

```pycon
>>> MyNumberModel.cli('', reader=specials)
Lorem Ipsum: 1 Value.
Dolor Sit Amet: X Value.

Total count: 2
```

```pycon
>>> MyNumberModel.cli('--value X', reader=specials)
Dolor Sit Amet
Value: X

Total count: 1
```

```pycon
>>> MyNumberModel.cli('--value ">0"', reader=specials)
Lorem Ipsum
Value: 1

Total count: 1
```

### DelimitedText

`DelimitedText` fields behave like a list of `Text` fields, where each part is separated by a given `str` delimiter. Each part is then matched individually.

```python
class Recipe(ModelBase):
    name = Text()
    ingredients = DelimitedText(delimiter=",")

def recipes(options: dict):
    yield {"name": "Sandwich", "ingredients": "bread,cheese"}
    yield {"name": "Hamburger", "ingredients": "bread,meat,dressing"}
```

```pycon
>>> Recipe.cli('--ingredients bread --exact', reader=recipes)
Sandwich: bread,cheese.
Hamburger: bread,meat,dressing.

Total count: 2
```

```pycon
>>> Recipe.cli('--ingredients cheese --exact', reader=recipes)
Sandwich
Ingredients: bread,cheese

Total count: 1
```

### Choice

`Choice` fields behave as `Text` fields but have a defined set of valid values. Prefix arguments are automatically completed to the valid choice.

```python
class Person(ModelBase):
    name = Text()
    gender = Choice(["Female", "Male", "Other"])

def people(options: dict):
    yield {"name": "Elvis", "gender": "Male"}
    yield {"name": "Elizabeth", "gender": "Female"}
```

```pycon
>>> Person.cli('', reader=people)
Elvis: Male.
Elizabeth: Female.

Total count: 2
```

```pycon
>>> Person.cli('--gender male', reader=people)
Elvis
Gender: Male

Total count: 1
```

```pycon
>>> Person.cli('--gender f', reader=people)
Elizabeth
Gender: Female

Total count: 1
```

```pycon
>>> Person.cli('--gender foo', reader=people)
Usage: ...

Error: Invalid value for '--gender': Valid choices are: Female, Male, Other
```

### Flag

`Flag` fields represent boolean "Yes" or "No" values. A value of `1`, `"1"` or `True` are treated as "Yes", otherwise it's a "No". `Flag` fields implement two filters, one to test for "Yes" values and one for "No" values, the latter prefixed with "non-".

```python
class Person(ModelBase):
    name = Text()
    alive = Flag()

def people(options: dict):
    yield {"name": "Elvis", "alive": 1}
    yield {"name": "Elizabeth", "alive": 0}
```

```pycon
>>> Person.cli('', reader=people)
Elvis: Alive.
Elizabeth: Non-Alive.

Total count: 2
```

```pycon
>>> Person.cli('--alive', reader=people)
Elvis
Alive: Yes

Total count: 1
```

```pycon
>>> Person.cli('--non-alive', reader=people)
Elizabeth
Alive: No

Total count: 1
```

### Field Parameters

Parameters common to all field types.

#### `default`

Define a default value used for fields where the value is missing.

```python
class Person(ModelBase):
    name = Text()
    gender = Choice(["Female", "Male", "Other"], default="Other")

def people(options: dict):
    yield {"name": "Totoro"}
```

```pycon
>>> Person.cli('', reader=people)
Totoro
Gender: Other

Total count: 1
```

#### `inclusive`

Treat multiple uses of this field's filters as a [logical disjunction](https://en.wikipedia.org/wiki/Classical_logic) (OR logic), rather than a [logical conjunction](https://en.wikipedia.org/wiki/Logical_conjunction) (AND logic), which is the default.

```python
class Person(ModelBase):
    name = Text()
    gender = Choice(["Female", "Male", "Other"], inclusive=True)

def people(options: dict):
    yield {"name": "Elvis", "gender": "Male"}
    yield {"name": "Elizabeth", "gender": "Female"}
    yield {"name": "Totoro", "gender": "Other"}
```

Multiple use of `--name` gives fewer results.

```pycon
>>> Person.cli('--name El', reader=people)
Elvis: Male.
Elizabeth: Female.

Total count: 2
```

```pycon
>>> Person.cli('--name El --name beth', reader=people)
Elizabeth
Gender: Female

Total count: 1
```

But multiple uses of `--gender` gives more results, since it has `inclusive=True`.

```pycon
>>> Person.cli('--gender other --gender male', reader=people)
Elvis: Male.
Totoro: Other.

Total count: 2
```

#### `skip_filters`

Don't add the given filter option for this field.


```python
class Person(ModelBase):
    name = Text()
    age = Number()
    height = Number(skip_filters=[Number.filter_number])
```

```pycon
>>> Person.cli('--help')
Usage: doctest.py [OPTIONS] [FILE]...

Options:
  -v, --verbose  Show more data.
  --brief        Show one line of data, regardless the level of verbose.
  --long         Show multiple lines of data, regardless the level of verbose.
  --show FIELD   Show given field only. Can be repeated to show multiple
                 fields in given order.
  --case         Use case sensitive filtering.
  --exact        Use exact match filtering.
  --regex        Use regular rexpressions when filtering.
  --inclusive    Use inclusive filtering that expand the result rather than
                 shrinking it.
  --sort FIELD   Sort results by given field.
  --group FIELD  Group results by given field.
  --desc         Sort results in descending order.
  --count FIELD  Print a breakdown of all values for given field.
  --help         Show this message and exit.

Field filters:
  --name TEXT   Filter on matching name.
  --age NUMBER  Filter on matching age (number comparison).
...
```

#### `keyname`

The item key for getting this field's value. Defaults to the same as the field property name, use this if it differs.

```python
class MyModel(ModelBase):
    name = Text(keyname="foo")

def reader(options: dict):
    yield {'foo': 'Lorem Ipsum'}
    yield {'foo': 'Dolor Sit Amet'}
```

```pycon
>>> MyModel.cli('', reader=reader)
Lorem Ipsum
Dolor Sit Amet

Total count: 2
```

#### `realname`

The name used to reference the field in command output. Defaults to a
title-case version of the field property name.

```python
class MyModel(ModelBase):
    name = Text()
    value = Number(realname="Foo")

def reader(options: dict):
    yield {'name': 'Lorem Ipsum', 'value': 1}
    yield {'name': 'Dolor Sit Amet', 'value': 2}
```

```pycon
>>> MyModel.cli('', reader=reader)
Lorem Ipsum: 1 Foo.
Dolor Sit Amet: 2 Foo.

Total count: 2
```

```pycon
>>> MyModel.cli('--value 1', reader=reader)
Lorem Ipsum
Foo: 1

Total count: 1
```

#### `optname`

The name used to substitute the `{optname}` variable in field filter arguments.
Defaults to field property name, but with `_` replaced with `-`.

```python
class MyModel(ModelBase):
    name = Text(optname="foo")

def reader(options: dict):
    yield {'foo': 'Lorem Ipsum'}
    yield {'foo': 'Dolor Sit Amet'}
```

```pycon
>>> MyModel.cli('--help', reader=reader)
Usage: doctest.py [OPTIONS]
<BLANKLINE>
Options:
  -v, --verbose  Show more data.
  --brief        Show one line of data, regardless the level of verbose.
  --long         Show multiple lines of data, regardless the level of verbose.
  --show FIELD   Show given field only. Can be repeated to show multiple
                 fields in given order.
  --case         Use case sensitive filtering.
  --exact        Use exact match filtering.
  --regex        Use regular rexpressions when filtering.
  --inclusive    Use inclusive filtering that expand the result rather than
                 shrinking it.
  --sort FIELD   Sort results by given field.
  --group FIELD  Group results by given field.
  --desc         Sort results in descending order.
  --count FIELD  Print a breakdown of all values for given field.
  --help         Show this message and exit.
<BLANKLINE>
Field filters:
  --foo TEXT  Filter on matching name.
...
```

#### `helpname`

The name used to substitute the `{helpname}` variable in field filter help
texts. Defaults to a lowercase version of `realname`.

```python
class MyModel(ModelBase):
    name = Text(helpname="foo")

def reader(options: dict):
    yield {'name': 'Lorem Ipsum'}
    yield {'name': 'Dolor Sit Amet'}
```

```pycon
>>> MyModel.cli('--help', reader=reader)
Usage: doctest.py [OPTIONS]
<BLANKLINE>
Options:
  -v, --verbose  Show more data.
  --brief        Show one line of data, regardless the level of verbose.
  --long         Show multiple lines of data, regardless the level of verbose.
  --show FIELD   Show given field only. Can be repeated to show multiple
                 fields in given order.
  --case         Use case sensitive filtering.
  --exact        Use exact match filtering.
  --regex        Use regular rexpressions when filtering.
  --inclusive    Use inclusive filtering that expand the result rather than
                 shrinking it.
  --sort FIELD   Sort results by given field.
  --group FIELD  Group results by given field.
  --desc         Sort results in descending order.
  --count FIELD  Print a breakdown of all values for given field.
  --help         Show this message and exit.
<BLANKLINE>
Field filters:
  --name TEXT  Filter on matching foo.
...
```

#### `typename`

The name used in the help text for the argument type of this field. Defaults to
the `name` property of the field class.

```python
class MyModel(ModelBase):
    name = Text(typename="FOO")

def reader(options: dict):
    yield {'name': 'Lorem Ipsum'}
    yield {'name': 'Dolor Sit Amet'}
```

```pycon
>>> MyModel.cli('--help', reader=reader)
Usage: doctest.py [OPTIONS]
<BLANKLINE>
Options:
  -v, --verbose  Show more data.
  --brief        Show one line of data, regardless the level of verbose.
  --long         Show multiple lines of data, regardless the level of verbose.
  --show FIELD   Show given field only. Can be repeated to show multiple
                 fields in given order.
  --case         Use case sensitive filtering.
  --exact        Use exact match filtering.
  --regex        Use regular rexpressions when filtering.
  --inclusive    Use inclusive filtering that expand the result rather than
                 shrinking it.
  --sort FIELD   Sort results by given field.
  --group FIELD  Group results by given field.
  --desc         Sort results in descending order.
  --count FIELD  Print a breakdown of all values for given field.
  --help         Show this message and exit.
<BLANKLINE>
Field filters:
  --name FOO  Filter on matching name.
...
```

#### `verbosity`

The level of `verbose` required for this field to be included in the output.

```python
class MyModel(ModelBase):
    name = Text()
    foo = Number(verbosity=1)
    bar = Number()
    baz = Number(verbosity=2)

def reader(options: dict):
    yield {'name': 'Lorem Ipsum', 'foo': 1, 'bar': 2, 'baz': 3}
    yield {'name': 'Dolor Sit Amet', 'foo': 4, 'bar': 5, 'baz': 6}
```

The fields `foo` and `baz` are not shown with default level of `verbose`:

```pycon
>>> MyModel.cli('', reader=reader)
Lorem Ipsum: 2 Bar.
Dolor Sit Amet: 5 Bar.

Total count: 2
```

With 1 level of `verbose` we see that `foo` is shown:

```pycon
>>> MyModel.cli('-v', reader=reader)
Lorem Ipsum
Foo: 1
Bar: 2

Dolor Sit Amet
Foo: 4
Bar: 5

Total count: 2
```

With 2 levels of `verbose` we see all the fields:

```pycon
>>> MyModel.cli('-vv', reader=reader)
Lorem Ipsum
Foo: 1
Bar: 2
Baz: 3

Dolor Sit Amet
Foo: 4
Bar: 5
Baz: 6

Total count: 2
```

Note that if a single item is found, the `verbose` level is automatically increased by 1:

```pycon
>>> MyModel.cli('--foo 1 -v', reader=reader)
Lorem Ipsum
Foo: 1
Bar: 2
Baz: 3

Total count: 1
```

Note that the `--brief` option blocks increased `verbose` levels:

```pycon
>>> MyModel.cli('-vvv --brief', reader=reader)
Lorem Ipsum: 2 Bar.
Dolor Sit Amet: 5 Bar.

Total count: 2
```

#### `standalone`

Set to `True` to have `FieldBase.format_long` return values for this field
as-is, without its `realname` label.

By default this is set to `True` for the first field defined on a model,
otherwise `False`.

```python
class Philosopher(ModelBase):
    name = Text(standalone=False)
    quote = Text(standalone=True)

def reader(options: dict):
    yield {'name': 'Aristotle', 'quote': '"Quality is not an act, it is a habit."'}
    yield {'name': 'Pascal', 'quote': '"You always admire what you don\'t understand."'}
```

```pycon
>>> Philosopher.cli('-v', reader=reader)
Name: Aristotle
"Quality is not an act, it is a habit."

Name: Pascal
"You always admire what you don't understand."

Total count: 2
```

#### `implied`

A dict of related field filters that are implied by filtering on this field.

```python
class Species(ModelBase):
    name = Text()
    type = Choice(['Mammal', 'Fish', 'Bird', 'Reptile', 'Amphibian'])
    gestation_period = Number(implied={'type': 'Mammal'})

def reader(options: dict):
    yield {'name': 'Human', 'type': 'Mammal', 'gestation_period': 280}
    yield {'name': 'Cat', 'type': 'Mammal', 'gestation_period': 65}
    yield {'name': 'Eagle', 'type': 'Bird', 'gestation_period': 0}
    yield {'name': 'Toad', 'type': 'Amphibian'}
```

```pycon
>>> Species.cli('--gestation-period "<100"', reader=reader)
Cat
Type: Mammal
Gestation Period: 65

Total count: 1
```

#### `styles`

Set the styles with which to display values of this field, as passed on to [click.style](https://click.palletsprojects.com/en/latest/api/#click.style).
