# Clicksearch

Clicksearch is a framework for writing CLI programs that filter a stream of data objects. Clicksearch lets you define a model of the objects your program should work with, and based on this model Clicksearch creates a CLI with options for filtering on the defined fields.

Clicksearch is based on the [Click](https://click.palletsprojects.com) framework, which handles all of the heavy lifting CLI work.

## The Basics

Let's start with a basic example on how to write a simple Clicksearch program.

### The Model

At the heart of Clicksearch is the model. Every Clicksearch program needs to define a subclass of the `ModelBase` class, that describes the supported data:

```python
class Person(ModelBase):
    name = Text()
    age = Number()
```

From this simple model you can launch your CLI program by calling the `ModelBase.cli` class method:

```pycon
>>> Person.cli('--help')
Usage: ... [OPTIONS] [FILE]...

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

Where:
  FIELD   One of: age, name.
  NUMBER  A number optionally prefixed by one of the supported comparison
          operators: ==, =, !=, !, <=, <, >=, >. With == being the default if
          only a number is given.
  TEXT    A text partially matching the field value. The --case, --regex and
          --exact options can be applied. If prefixed with ! the match is
          negated.
```

> :exclamation: The first argument to `Person.cli` is the command line arguments as a string. This is optional and generally not required when launching the program from a terminal, but here we need it since we are launching from the Python REPL.

We can see from the `--help` output that we have a bunch of basic options, that will be the same for all Clicksearch programs, and then we have a a few options called *field filters*, that are based on the fields defined on the model.

### The Reader

The next thing Clicksearch needs is a data source, called a _reader_. In Python terms the reader should be a `Callable[[Mapping], Iterable[Mapping]]` object. That is: it should be a callable object that takes a single `dict` argument (the parsed [Click](https://click.palletsprojects.com) parameters) and returns some sort of object that can be iterated over to generate the data objects that Clicksearch should work with.

In its simplest form this can be a function that return, for instance, a `list`:

```python
def people(options: dict):
    return [
        {'name': 'Alice Anderson', 'age': 42},
        {'name': 'Bob Balderson', 'age': 27},
    ]
```

Or perhaps be a Python generator:

```python
def people(options: dict):
    yield {'name': 'Alice Anderson', 'age': 42}
    yield {'name': 'Bob Balderson', 'age': 27}
```

Provide the reader to `Person.cli` with the `reader` keyword argument. Now you are ready to start using the CLI program! Call the `Person.cli` method with the command line options as the first argument:

```pycon
>>> Person.cli('', reader=people)
Alice Anderson: 42 Age.
Bob Balderson: 27 Age.

Total count: 2
```

```pycon
>>> Person.cli('--verbose', reader=people)
Alice Anderson
Age: 42

Bob Balderson
Age: 27

Total count: 2
```

```pycon
>>> Person.cli('--age 27', reader=people)
Bob Balderson
Age: 27

Total count: 1
```

### The Script

Your complete CLI program would then look something like this:

[DOCTEST_BREAK]::

```python
#!/usr/bin/env python3

from clicksearch import ModelBase, Text, Number

class Person(ModelBase):
    name = Text()
    age = Number()

def people(options: dict):
    yield {'name': 'Alice Anderson', 'age': 42}
    yield {'name': 'Bob Balderson', 'age': 27}

if __name__ == '__main__':
    Person.cli(reader=people)
```

[DOCTEST_CONTINUE]::

## Fields

Fields are the objects used to compose your model. Clicksearch comes with a number of basic field types built-in, but you can of course also define your own field type by subclassing from the `FieldBase` class (or from any other built-in field type).

### Text

`Text` fields support `str` values and implement a single filter option that matches any part of the field value. In the example below the option will be given the default name `--name`. The behavior of the `Text` field filter can then be further controlled with the `--case`, `--exact` and `--regex` options.

The examples below use the same model and reader from previous section.

#### `--case`

The `--case` option makes the `Text` field filter case sensitive.

```pycon
>>> Person.cli('--name "bob" --case', reader=people)

Total count: 0
```

```pycon
>>> Person.cli('--name "Bob" --case', reader=people)
Bob Balderson
Age: 27

Total count: 1
```

#### `--exact`

The `--exact` option makes the `Text` field filter require a full match.

```pycon
>>> Person.cli('--name "bob" --exact', reader=people)

Total count: 0
```

```pycon
>>> Person.cli('--name "bob balderson" --exact', reader=people)
Bob Balderson
Age: 27

Total count: 1
```

#### `--regex`

The `--regex` option makes the `Text` field filter operate as a [regular expression](https://docs.python.org/3/library/re.html).

```pycon
>>> Person.cli('--name "\\b[anderson]+\\b" --regex', reader=people)
Alice Anderson
Age: 42

Total count: 1
```

```pycon
>>> Person.cli('--name "\\b[blanderson]+\\b" --regex', reader=people)
Alice Anderson: 42 Age.
Bob Balderson: 27 Age.

Total count: 2
```

```pycon
>>> Person.cli('--name "b]d r[g}x" --regex', reader=people)
Usage: ...

Error: Invalid value for '--name': Invalid regular expression
```

### Number

`Number` fields support numeric values and implement a single filter that allows basic comparisons with the field value. In the example below the option will be given the default name `--age`. The supported comparison operators are: `==` (the default), `!=`, `<`, `<=`, `>` and `>=`.

The examples below use the same model and reader from previous section.

```pycon
>>> Person.cli('--age 42', reader=people)
Alice Anderson
Age: 42

Total count: 1
```

```pycon
>>> Person.cli('--age "<50"', reader=people)
Alice Anderson: 42 Age.
Bob Balderson: 27 Age.

Total count: 2
```

```pycon
>>> Person.cli('--age ">=42"', reader=people)
Alice Anderson
Age: 42

Total count: 1
```

```pycon
>>> Person.cli('--age "X"', reader=people)
Usage: ...

Error: Invalid value for '--age': X
```

#### Specials

`Number` fields can also be configured to accept non-numeric values with the `specials` parameter. Such special values only support direct equality comparison.

```python
class Gift(ModelBase):
    name = Text()
    price = Number(specials=['X'])

def gifts(options: dict):
    yield {'name': 'Socks', 'price': 7}
    yield {'name': 'Voucher', 'price': 'X'}
```

```pycon
>>> Gift.cli('', reader=gifts)
Socks: 7 Price.
Voucher: X Price.

Total count: 2
```

```pycon
>>> Gift.cli('--price X', reader=gifts)
Voucher
Price: X

Total count: 1
```

```pycon
>>> Gift.cli('--price ">0"', reader=gifts)
Socks
Price: 7

Total count: 1
```

#### Prefix Labels

Since `Number` fields include a label in the brief output format, the `prelabeled` option can be used to control whether that label should go before or after the value.

```python
class Person(ModelBase):
    name = Text()
    age = Number(prelabeled=True)
```

```pycon
>>> Person.cli('', reader=people)
Alice Anderson: Age 42.
Bob Balderson: Age 27.

Total count: 2
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
    yield {"name": "Alice Anderson", "gender": "Female"}
    yield {"name": "Bob Balderson", "gender": "Male"}
```

```pycon
>>> Person.cli('', reader=people)
Alice Anderson: Female.
Bob Balderson: Male.

Total count: 2
```

```pycon
>>> Person.cli('--gender male', reader=people)
Bob Balderson
Gender: Male

Total count: 1
```

```pycon
>>> Person.cli('--gender f', reader=people)
Alice Anderson
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
    yield {"name": "Bob Balderson", "alive": 1}
    yield {"name": "Alice Anderson", "alive": 0}
```

```pycon
>>> Person.cli('', reader=people)
Bob Balderson: Alive.
Alice Anderson: Non-Alive.

Total count: 2
```

```pycon
>>> Person.cli('--alive', reader=people)
Bob Balderson
Alive: Yes

Total count: 1
```

```pycon
>>> Person.cli('--non-alive', reader=people)
Alice Anderson
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
    yield {"name": "Alice Anderson", "gender": "Female"}
    yield {"name": "Bob Balderson", "gender": "Male"}
    yield {"name": "Totoro", "gender": "Other"}
```

Multiple use of `--name` gives fewer results.

```pycon
>>> Person.cli('--name son', reader=people)
Alice Anderson: Female.
Bob Balderson: Male.

Total count: 2
```

```pycon
>>> Person.cli('--name son --name ander', reader=people)
Alice Anderson
Gender: Female

Total count: 1
```

But multiple uses of `--gender` gives more results, since it has `inclusive=True`.

```pycon
>>> Person.cli('--gender other --gender male', reader=people)
Bob Balderson: Male.
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
Usage: ...

Options: ...

Field filters:
  --name TEXT   Filter on matching name.
  --age NUMBER  Filter on matching age (number comparison).
...
```

#### `keyname`

The item key for getting this field's value. Defaults to the the field property name if not set.

```python
class Event(ModelBase):
    name = Text()
    date = Text(keyname="ISO-8601")

def events(options: dict):
    yield {'name': 'Battle of Hastings', 'ISO-8601': '1066-10-14T13:07:53+0000'}
    yield {'name': '9/11', 'ISO-8601': '2001-09-11T08:46:00-0500'}
```

```pycon
>>> Event.cli('--help', reader=events)
Usage: ...

Options: ...

Field filters:
  --name TEXT  Filter on matching name.
  --date TEXT  Filter on matching date.
...
```

```pycon
>>> Event.cli('-v', reader=events)
Battle of Hastings
Date: 1066-10-14T13:07:53+0000

9/11
Date: 2001-09-11T08:46:00-0500

Total count: 2
```

#### `realname`

The name used to reference the field in command output. Defaults to a title-case version of the field property name with `_` replaced with ` `.

```python
class Event(ModelBase):
    name = Text()
    ISO8601 = Text(realname="Date")

def events(options: dict):
    yield {'name': 'Battle of Hastings', 'ISO8601': '1066-10-14T13:07:53+0000'}
    yield {'name': '9/11', 'ISO8601': '2001-09-11T08:46:00-0500'}
```

```pycon
>>> Event.cli('--help', reader=events)
Usage: ...

Options: ...

Field filters:
  --name TEXT  Filter on matching name.
  --date TEXT  Filter on matching date.
...
```

```pycon
>>> Event.cli('-v', reader=events)
Battle of Hastings
Date: 1066-10-14T13:07:53+0000

9/11
Date: 2001-09-11T08:46:00-0500

Total count: 2
```

#### `helpname`

The name used to substitute the `{helpname}` variable in field filter help texts. Defaults to a lower case version of `realname`.

```python
class Event(ModelBase):
    name = Text()
    ISO8601 = Text(helpname="date")
```


```pycon
>>> Event.cli('--help', reader=events)
Usage: ...

Options: ...

Field filters:
  --name    TEXT  Filter on matching name.
  --iso8601 TEXT  Filter on matching date.
...
```

```pycon
>>> Event.cli('-v', reader=events)
Battle of Hastings
Iso8601: 1066-10-14T13:07:53+0000

9/11
Iso8601: 2001-09-11T08:46:00-0500

Total count: 2
```

#### `optname`

The name used to substitute the `{optname}` variable in field filter arguments. Defaults to a lower case version of `realname` with ` ` replaced with `-`.

```python
class Event(ModelBase):
    name = Text()
    ISO8601 = Text(optname="date")
```


```pycon
>>> Event.cli('--help', reader=events)
Usage: ...

Options: ...

Field filters:
  --name TEXT  Filter on matching name.
  --date TEXT  Filter on matching iso8601.
...
```

```pycon
>>> Event.cli('-v', reader=events)
Battle of Hastings
Iso8601: 1066-10-14T13:07:53+0000

9/11
Iso8601: 2001-09-11T08:46:00-0500

Total count: 2
```

#### `typename`

The name used in the help text for the argument type of this field. Defaults to the `name` property of the field class.

```python
class Event(ModelBase):
    name = Text()
    ISO8601 = Text(typename="DATE")
```

```pycon
>>> Event.cli('--help', reader=events)
Usage: ...

Options: ...

Field filters:
  --name    TEXT  Filter on matching name.
  --iso8601 DATE  Filter on matching iso8601.
...
```

```pycon
>>> Event.cli('-v', reader=events)
Battle of Hastings
Iso8601: 1066-10-14T13:07:53+0000

9/11
Iso8601: 2001-09-11T08:46:00-0500

Total count: 2
```

#### `verbosity`

The level of `verbose` required for this field to be included in the output.

```python
class Book(ModelBase):
    title = Text()
    author = Text()
    author_sorted = Text(verbosity=2)
    pages = Number(verbosity=1)

def books(options: dict):
    yield {'title': 'Moby Dick', 'author': 'Herman Melville', 'author_sorted': 'Melville, Herman', 'pages': 720}
    yield {'title': 'Pride and Prejudice', 'author': 'Jane Austen', 'author_sorted': 'Austen, Jane', 'pages': 416}
```

The fields `pages` and `author_sorted` are not shown with default level of `verbose`:

```pycon
>>> Book.cli('', reader=books)
Moby Dick: Herman Melville.
Pride and Prejudice: Jane Austen.

Total count: 2
```

With 1 level of `verbose` we see that `pages` is shown:

```pycon
>>> Book.cli('-v', reader=books)
Moby Dick
Author: Herman Melville
Pages: 720

Pride and Prejudice
Author: Jane Austen
Pages: 416

Total count: 2
```

With 2 levels of `verbose` we see all the fields:

```pycon
>>> Book.cli('-vv', reader=books)
Moby Dick
Author: Herman Melville
Author Sorted: Melville, Herman
Pages: 720

Pride and Prejudice
Author: Jane Austen
Author Sorted: Austen, Jane
Pages: 416

Total count: 2
```

Note that if a single item is found, the `verbose` level is automatically increased by 1:

```pycon
>>> Book.cli('--author Melville', reader=books)
Moby Dick
Author: Herman Melville
Pages: 720

Total count: 1
```

Note that the `--brief` option prevents increased `verbose` levels:

```pycon
>>> Book.cli('-vvv --brief', reader=books)
Moby Dick: Herman Melville.
Pride and Prejudice: Jane Austen.

Total count: 2
```

#### `unlabeled`

Set to `True` to use the values for this field as-is, without its `realname` label.

By default this is set to `True` for the first field defined on a model, otherwise `False`.

```python
class Philosopher(ModelBase):
    name = Text(unlabeled=False)
    quote = Text(unlabeled=True)

def philosophers(options: dict):
    yield {'name': 'Aristotle', 'quote': '"Quality is not an act, it is a habit."'}
    yield {'name': 'Pascal', 'quote': '"You always admire what you don\'t understand."'}
```

```pycon
>>> Philosopher.cli('-v', reader=philosophers)
Name: Aristotle
"Quality is not an act, it is a habit."

Name: Pascal
"You always admire what you don't understand."

Total count: 2
```

This should also affect labels used in the brief format, e.g. for `Number` fields.

```python
class Toplist(ModelBase):
    name = Text()
    rank = Number(unlabeled=True)

def philosophers(options: dict):
    yield {'name': 'Aristotle', 'rank': 1}
    yield {'name': 'Pascal', 'rank': 2}
```

```pycon
>>> Toplist.cli('', reader=philosophers)
Aristotle: 1.
Pascal: 2.

Total count: 2
```

#### `implied`

A string specifying a set of default filters to apply when this field is used. The syntax for this string is the same as if the options were given on the command line. The implied filters are only applied if the targeted field does not have any filters set.

```python
class Species(ModelBase):
    name = Text()
    animal_type = Choice(
        ['Mammal', 'Fish', 'Bird', 'Reptile', 'Amphibian'],
        keyname="type",
        optname="type",
        realname="Type",
        inclusive=True,
    )
    gestation_period = Number(implied="--type Mammal", optname="gp")

def reader(options: dict):
    yield {'name': 'Human', 'type': 'Mammal', 'gestation_period': 280}
    yield {'name': 'Cat', 'type': 'Mammal', 'gestation_period': 65}
    yield {'name': 'Eagle', 'type': 'Bird', 'gestation_period': 0}
    yield {'name': 'Toad', 'type': 'Amphibian'}
```

The "Eagle" and the "Toad" are excluded from the output because the `--gp` option implies `--type Mammal`:


```pycon
>>> Species.cli('--gp "<100"', reader=reader)
Cat
Type: Mammal
Gestation Period: 65

Total count: 1
```

```pycon
>>> Species.cli('--sort gp', reader=reader)
Cat: Mammal. 65 Gestation Period.
Human: Mammal. 280 Gestation Period.

Total count: 2
```

```pycon
>>> Species.cli('--group gp', reader=reader)
[ 65 Gestation Period ]
Cat: Mammal. 65 Gestation Period.

[ 280 Gestation Period ]
Human: Mammal. 280 Gestation Period.

Total count: 2
```

```pycon
>>> Species.cli('--show gp', reader=reader)
Human: 280 Gestation Period.
Cat: 65 Gestation Period.

Total count: 2
```

```pycon
>>> Species.cli('--count gp', reader=reader)

[ Gestation Period counts ]
280 Gestation Period: 1
65 Gestation Period: 1

Total count: 2
```

If `animal_type` is explicitly filtered then the implied `--type` is ignored:

```pycon
>>> Species.cli('--sort gp --type-isnt Mammal', reader=reader)
Toad: Amphibian.
Eagle: Bird. 0 Gestation Period.

Total count: 2
```

#### `styles`

Set the styles with which to display values of this field, as passed on to [click.style](https://click.palletsprojects.com/en/latest/api/#click.style).
