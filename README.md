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
  --or FIELD     Treat multiple tests for given field with logical
                 disjunction, i.e. OR-logic instead of AND-logic.
  --inclusive    Treat multiple tests for different fields with logical
                 disjunction, i.e. OR-logic instead of AND-logic.
  --sort FIELD   Sort results by given field.
  --desc         Sort results in descending order.
  --group FIELD  Group results by given field.
  --count FIELD  Print a breakdown of all values for given field.
  --version      Show the version and exit.
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

In its simplest form this can be a function that returns, for instance, a `list`:

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
Alice Anderson: Age 42.
Bob Balderson: Age 27.

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

## Command Line Options

These are the basic command line options available in all Clicksearch programs.

To examplify the different use cases, the following model and reader will be used:

```python
class Employee(ModelBase):
    name = Text()
    title = Text()
    gender = Choice(["Female", "Male", "Other"], autofilter=True)
    salary = Number(autofilter=True)


def employees(options: dict):
    yield {
        'name': 'Alice Anderson',
        'title': 'Sales Director',
        'salary': 4200,
        'gender': 'Female',
    }
    yield {
        'name': 'Bob Balderson',
        'title': 'Sales Representative',
        'salary': 2700,
        'gender': 'Male',
    }
    yield {
        'name': 'Charlotte Carlson',
        'title': 'Sales Representative',
        'salary': 2200,
        'gender': 'Female',
    }
    yield {
        'name': 'Totoro',
        'title': 'Company Mascot',
    }
```

### `-v`, `--verbose`

The `--verbose` option is used to show more details of the resulting items. By default items are shown using the "brief" format, using a single line per item. Adding a level of verbose will switch to using the "long" format, using a single line per item field.

See also the `verbosity` field parameter for further use cases of the `--verbose` option.

```pycon
>>> Employee.cli('--verbose', reader=employees)
Alice Anderson
Title: Sales Director
Gender: Female
Salary: 4200

Bob Balderson
Title: Sales Representative
Gender: Male
Salary: 2700

Charlotte Carlson
Title: Sales Representative
Gender: Female
Salary: 2200

Totoro
Title: Company Mascot

Total count: 4
```

### `--brief`

The `--brief` option forces the use of the "brief" format, using a single line per item, regardless of the level of verbose. This is mainly useful to ensure that the brief format is used also when a single item is found.

```pycon
>>> Employee.cli('--gender male --brief', reader=employees)
Bob Balderson: Sales Representative. Male. Salary 2700.

Total count: 1
```

### `--long`

The `--long` option forces the use of the "long" format, using a single line per item field, regardless of the level of verbose.

```pycon
>>> Employee.cli('--long', reader=employees)
Alice Anderson
Title: Sales Director
Gender: Female
Salary: 4200

Bob Balderson
Title: Sales Representative
Gender: Male
Salary: 2700

Charlotte Carlson
Title: Sales Representative
Gender: Female
Salary: 2200

Totoro
Title: Company Mascot

Total count: 4
```

### `--show`

The `--show` option can be used to control what fields to display.

```pycon
>>> Employee.cli('--show gender --show salary', reader=employees)
Alice Anderson: Female. Salary 4200.
Bob Balderson: Male. Salary 2700.
Charlotte Carlson: Female. Salary 2200.

Total count: 3
```

```pycon
>>> Employee.cli('--show salary --show title --long', reader=employees)
Alice Anderson
Salary: 4200
Title: Sales Director

Bob Balderson
Salary: 2700
Title: Sales Representative

Charlotte Carlson
Salary: 2200
Title: Sales Representative

Total count: 3
```

### `--case`

The `--case` option makes the `Text` field filter case sensitive.

```pycon
>>> Employee.cli('--name "bob" --case', reader=employees)

Total count: 0
```

```pycon
>>> Employee.cli('--name "Bob" --case', reader=employees)
Bob Balderson
Title: Sales Representative
Gender: Male
Salary: 2700

Total count: 1
```

### `--exact`

The `--exact` option makes the `Text` field filter require a full match.

```pycon
>>> Employee.cli('--name "bob" --exact', reader=employees)

Total count: 0
```

```pycon
>>> Employee.cli('--name "bob balderson" --exact', reader=employees)
Bob Balderson
Title: Sales Representative
Gender: Male
Salary: 2700

Total count: 1
```

### `--regex`

The `--regex` option makes the `Text` field filter operate as a [regular expression](https://docs.python.org/3/library/re.html).

```pycon
>>> Employee.cli('--name "\\b[anderson]+\\b" --regex', reader=employees)
Alice Anderson
Title: Sales Director
Gender: Female
Salary: 4200

Total count: 1
```

```pycon
>>> Employee.cli('--name "\\b[blanderson]+\\b" --regex', reader=employees)
Alice Anderson: Sales Director. Female. Salary 4200.
Bob Balderson: Sales Representative. Male. Salary 2700.

Total count: 2
```

```pycon
>>> Employee.cli('--name "b]d r[g}x" --regex', reader=employees)
Usage: ...

Error: Invalid value for '--name': Invalid regular expression
```

### `--or`

The `--or` option treats multiple uses of a given field filter as a [logical disjunction](https://en.wikipedia.org/wiki/Classical_logic) (OR logic), rather than a [logical conjunction](https://en.wikipedia.org/wiki/Logical_conjunction) (AND logic), which is the default unless the field is specifically configured as a inclusive field.

Without `--or`, multiple uses of the same field filter give fewer results.

```pycon
>>> Employee.cli('--name "C" --name "Anderson" --brief', reader=employees)
Alice Anderson: Sales Director. Female. Salary 4200.

Total count: 1
```

Compared to when `--or` is used:

```pycon
>>> Employee.cli('--name "C" --name "Anderson" --or name --brief', reader=employees)
Alice Anderson: Sales Director. Female. Salary 4200.
Charlotte Carlson: Sales Representative. Female. Salary 2200.

Total count: 2
```

### `--inclusive`

The `--inclusive` option treats multiple uses of different field filters as a [logical disjunction](https://en.wikipedia.org/wiki/Classical_logic) (OR logic), rather than a [logical conjunction](https://en.wikipedia.org/wiki/Logical_conjunction) (AND logic), which is the default.

Without `--inclusive`, multiple uses of different filters give fewer results:

```pycon
>>> Employee.cli('--gender female --title "sales rep" --brief', reader=employees)
Charlotte Carlson: Sales Representative. Female. Salary 2200.

Total count: 1
```

Compared to when `--inclusive` is used:

```pycon
>>> Employee.cli('--gender female --title "sales rep" --inclusive', reader=employees)
Alice Anderson: Sales Director. Female. Salary 4200.
Bob Balderson: Sales Representative. Male. Salary 2700.
Charlotte Carlson: Sales Representative. Female. Salary 2200.

Total count: 3
```

### `--sort`

The `--sort` option controls the order in which resulting items are displayed.

```pycon
>>> Employee.cli('--sort salary', reader=employees)
Charlotte Carlson: Sales Representative. Female. Salary 2200.
Bob Balderson: Sales Representative. Male. Salary 2700.
Alice Anderson: Sales Director. Female. Salary 4200.

Total count: 3
```

```pycon
>>> Employee.cli('--sort gender', reader=employees)
Alice Anderson: Sales Director. Female. Salary 4200.
Charlotte Carlson: Sales Representative. Female. Salary 2200.
Bob Balderson: Sales Representative. Male. Salary 2700.

Total count: 3
```

### `--desc`

The `--desc` option switches the `--sort` and `--group` options to use descending order.

```pycon
>>> Employee.cli('--sort salary --desc', reader=employees)
Alice Anderson: Sales Director. Female. Salary 4200.
Bob Balderson: Sales Representative. Male. Salary 2700.
Charlotte Carlson: Sales Representative. Female. Salary 2200.

Total count: 3
```

### `--group`

The `--group` option displays the resulting items in groups by the target field values.

```pycon
>>> Employee.cli('--group title', reader=employees)
[ Company Mascot ]

Totoro: Company Mascot.

[ Sales Director ]

Alice Anderson: Sales Director. Female. Salary 4200.

[ Sales Representative ]

Bob Balderson: Sales Representative. Male. Salary 2700.
Charlotte Carlson: Sales Representative. Female. Salary 2200.

Total count: 4
```

### `--count`

The `--count` options adds a breakdown of all values for a given field.

```pycon
>>> Employee.cli('--count title', reader=employees)
[ Title counts ]

Sales Representative: 2
Sales Director:       1
Company Mascot:       1

Total count: 4
```

## Fields

Fields are the objects used to compose your model. Clicksearch comes with a number of basic field types built-in, but you can of course also define your own field type by subclassing from the `FieldBase` class (or from any other built-in field type).

### Text

`Text` fields support `str` values and implement a single filter option that matches any part of the field value.

For examples of this field in use see any of the previous sections, and especially those of the `--case`, `--exact` and `--regex` command line options.

### Number

`Number` fields support numeric values and implement a single filter that allows basic comparisons with the field value. In the example below the option will be given the default name `--age`. The supported comparison operators are: `==` (the default), `!=`, `<`, `<=`, `>` and `>=`.

The examples below use the same `Person` model and reader from previous section.

```pycon
>>> Person.cli('--age 42', reader=people)
Alice Anderson
Age: 42

Total count: 1
```

```pycon
>>> Person.cli('--age "<50"', reader=people)
Alice Anderson: Age 42.
Bob Balderson: Age 27.

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

#### `specials`

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
Socks: Price 7.
Voucher: Price X.

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

### Count

`Count` behave like `Number` fields but switch the label and value around in the brief format. If the name of the field is one that can have a count before it, then it is probably a `Count` rather than a `Number`.


```python
class Inventory(ModelBase):
    name = Text()
    price = Number()
    in_stock = Count()

def products(options: dict):
    yield {'name': 'Milk', 'price': 7, 'in_stock': 29}
    yield {'name': 'Yoghurt', 'price': 11, 'in_stock': 15}
```

```pycon
>>> Inventory.cli('', reader=products)
Milk: Price 7. 29 In Stock.
Yoghurt: Price 11. 15 In Stock.

Total count: 2
```

### DelimitedText

`DelimitedText` fields behave like a list of `Text` fields, where each part is separated by a given `str` delimiter. Each part is then matched individually.

```python
class Recipe(ModelBase):
    name = Text()
    ingredients = DelimitedText(delimiter=",", optname="ingredient")

def recipes(options: dict):
    yield {"name": "Sandwich", "ingredients": "bread,cheese"}
    yield {"name": "Hamburger", "ingredients": "bread,meat,dressing"}
    yield {"name": "Beef Wellington", "ingredients": "meat,ham,mushrooms,pastry"}
```

```pycon
>>> Recipe.cli('--exact --ingredient bread', reader=recipes)
Sandwich: bread,cheese.
Hamburger: bread,meat,dressing.

Total count: 2
```

```pycon
>>> Recipe.cli('--exact --ingredient mushrooms', reader=recipes)
Beef Wellington
Ingredients: meat,ham,mushrooms,pastry

Total count: 1
```

This also works with negated text matching:

```pycon
>>> Recipe.cli('--exact --ingredient "!cheese" --ingredient "!pastry"', reader=recipes)
Hamburger
Ingredients: bread,meat,dressing

Total count: 1
```

### Choice

`Choice` fields behave like `Text` fields but have a defined set of valid values. Prefix arguments are automatically completed to the valid choice.

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

Error: Invalid value for '--gender': Valid choices are: female, male, other
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

#### `truename` and `falsename`

The `truename` and `falsename` options can be used to configure what is displayed when the `Flag` value is true or false, respectively.

```python
class Person(ModelBase):
    name = Text()
    alive = Flag(truename="Alive and kickin'", falsename="Dead as a dojo")
```

```pycon
>>> Person.cli('', reader=people)
Bob Balderson: Alive and kickin'.
Alice Anderson: Dead as a dojo.

Total count: 2
```

### MarkupText

`MarkupText` fields represent text fields that have HTML-like markup that
should be parsed. HTML-like tags in the values will be replaced with ASCII
styles before displayed.

```python
class WebPage(ModelBase):
    url = Text(realname="URL")
    body = MarkupText()

def pages(options: dict):
    yield {"url": "https://thecompany.com", "body": "<h1>The Company</h1>\nWelcome to our <b>company</b>!"}
```

```pycon
>>> WebPage.cli('', reader=pages)
https://thecompany.com
Body: The Company
Welcome to our company!

Total count: 1
```

```pycon
>>> WebPage.cli('--body "our company"', reader=pages)
https://thecompany.com
Body: The Company
Welcome to our company!

Total count: 1
```

```pycon
>>> WebPage.cli('--body "<b>"', reader=pages)

Total count: 0
```

### FieldBase

`FieldBase` is the base class of all other fields, and not generally intended for direct use in models. The parameters available on `FieldBase` -- and therefore all other fields -- are listed below.

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

Using the example of `Employee` from above with a slightly updated model:

```python
class Employee(ModelBase):
    name = Text()
    title = Text(inclusive=True)
    gender = Choice(["Female", "Male", "Other"], inclusive=True, default="Other")
    salary = Number()
```

Multiple use of `--name` gives fewer results:

```pycon
>>> Employee.cli('--name erson', reader=employees)
Alice Anderson: Sales Director. Female. Salary 4200.
Bob Balderson: Sales Representative. Male. Salary 2700.

Total count: 2
```

```pycon
>>> Employee.cli('--name erson --name and --brief', reader=employees)
Alice Anderson: Sales Director. Female. Salary 4200.

Total count: 1
```

But multiple uses of `--gender` gives more results, since it has `inclusive=True`:

```pycon
>>> Employee.cli('--gender other --gender male', reader=employees)
Bob Balderson: Sales Representative. Male. Salary 2700.
Totoro: Company Mascot. Other.

Total count: 2
```

Same with multiple use of `--title`:

```pycon
>>> Employee.cli('--title rep --title dir', reader=employees)
Alice Anderson: Sales Director. Female. Salary 4200.
Bob Balderson: Sales Representative. Male. Salary 2700.
Charlotte Carlson: Sales Representative. Female. Salary 2200.

Total count: 3
```

However, mixed use of `--gender` and `--title` are *not* mutually inclusive.

```pycon
>>> Employee.cli('--title rep --title dir --gender female', reader=employees)
Alice Anderson: Sales Director. Female. Salary 4200.
Charlotte Carlson: Sales Representative. Female. Salary 2200.

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
    ISO_8601 = Text(realname="Date")

def events(options: dict):
    yield {'name': 'Battle of Hastings', 'ISO_8601': '1066-10-14T13:07:53+0000'}
    yield {'name': '9/11', 'ISO_8601': '2001-09-11T08:46:00-0500'}
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
    ISO_8601 = Text(helpname="date")
```


```pycon
>>> Event.cli('--help', reader=events)
Usage: ...

Options: ...

Field filters:
  --name     TEXT  Filter on matching name.
  --iso-8601 TEXT  Filter on matching date.
...
```

```pycon
>>> Event.cli('-v', reader=events)
Battle of Hastings
Iso 8601: 1066-10-14T13:07:53+0000

9/11
Iso 8601: 2001-09-11T08:46:00-0500

Total count: 2
```

#### `optname`

The name used to substitute the `{optname}` variable in field filter arguments. Defaults to a lower case version of `realname` with ` ` replaced with `-`.

```python
class Event(ModelBase):
    name = Text()
    ISO_8601 = Text(optname="date")
```


```pycon
>>> Event.cli('--help', reader=events)
Usage: ...

Options: ...

Field filters:
  --name TEXT  Filter on matching name.
  --date TEXT  Filter on matching iso 8601.
...
```

```pycon
>>> Event.cli('-v', reader=events)
Battle of Hastings
Iso 8601: 1066-10-14T13:07:53+0000

9/11
Iso 8601: 2001-09-11T08:46:00-0500

Total count: 2
```

#### `optalias`

An alternative option name to use, typically when a short version is required.

```python
class Employee(ModelBase):
    name = Text()
    title = Text(inclusive=True)
    gender = Choice(["Female", "Male", "Other"], inclusive=True, default="Other", optalias="-g")
    salary = Number()
```

```pycon
>>> Employee.cli('--help', reader=employees)
Usage: ...

Options: ...

Field filters:
  --name TEXT           Filter on matching name.
  --title TEXT          Filter on matching title.
  -g, --gender GENDER   Filter on matching gender.
  --gender-isnt GENDER  Filter on non-matching gender.
  --salary NUMBER       Filter on matching salary (number comparison).
...
```

```pycon
>>> Employee.cli('-g Other', reader=employees)
Totoro
Title: Company Mascot
Gender: Other

Total count: 1
```

#### `typename`

The name used in the help text for the argument type of this field. Defaults to the `name` property of the field class.

```python
class Event(ModelBase):
    name = Text()
    ISO_8601 = Text(typename="DATE")
```

```pycon
>>> Event.cli('--help', reader=events)
Usage: ...

Options: ...

Field filters:
  --name     TEXT  Filter on matching name.
  --iso-8601 DATE  Filter on matching iso 8601.
...
```

```pycon
>>> Event.cli('-v', reader=events)
Battle of Hastings
Iso 8601: 1066-10-14T13:07:53+0000

9/11
Iso 8601: 2001-09-11T08:46:00-0500

Total count: 2
```

#### `verbosity`

The level of `verbose` required for this field to be included in the output.

```python
class Book(ModelBase):
    title = Text()
    author = Text()
    author_sorted = Text(verbosity=2)
    pages = Count(verbosity=1)

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

#### `redirect_args`

Set to `True` to redirect all positional arguments to the **first** filter option for this field.

```python
class Employee(ModelBase):
    name = Text(redirect_args=True)
    title = Text(inclusive=True)
    gender = Choice(["Female", "Male", "Other"], inclusive=True, default="Other")
    salary = Number()
```

```pycon
>>> Employee.cli('Bob', reader=employees)
Bob Balderson
Title: Sales Representative
Gender: Male
Salary: 2700

Total count: 1
```

#### `autofilter`

Set to `True` to automatically exclude all items where this field is missing, when this field is referenced by any option (e.g. `--sort`, `--count`, `--show`).

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
    gestation_period = Number(optname="gp", autofilter=True)

def species(options: dict):
    yield {'name': 'Human', 'type': 'Mammal', 'gestation_period': 280}
    yield {'name': 'Cat', 'type': 'Mammal', 'gestation_period': 65}
    yield {'name': 'Eagle', 'type': 'Bird', 'gestation_period': None}
    yield {'name': 'Toad', 'type': 'Amphibian'}
```

The "Eagle" and the "Toad" are excluded from the output because the they do not provide a value for the `gestation_period` field:

```pycon
>>> Species.cli('--gp "<100"', reader=species)
Cat
Type: Mammal
Gestation Period: 65

Total count: 1
```

```pycon
>>> Species.cli('--sort "gestation period"', reader=species)
Cat: Mammal. Gestation Period 65.
Human: Mammal. Gestation Period 280.

Total count: 2
```

```pycon
>>> Species.cli('--group "gestation period"', reader=species)
[ Gestation Period 65 ]
Cat: Mammal. Gestation Period 65.

[ Gestation Period 280 ]
Human: Mammal. Gestation Period 280.

Total count: 2
```

```pycon
>>> Species.cli('--show "gestation period"', reader=species)
Human: Gestation Period 280.
Cat: Gestation Period 65.

Total count: 2
```

```pycon
>>> Species.cli('--count "gestation period"', reader=species)

[ Gestation Period counts ]

Gestation Period 280: 1
Gestation Period 65:  1

Total count: 2
```

```pycon
>>> Species.cli('--type-isnt Mammal', reader=species)
Eagle: Bird.
Toad: Amphibian.

Total count: 2
```

```pycon
>>> Species.cli('--sort "gestation period" --type-isnt Mammal', reader=species)

Total count: 0
```

#### `styles`

Set the styles with which to display values of this field, as passed on to [click.style](https://click.palletsprojects.com/en/latest/api/#click.style).
