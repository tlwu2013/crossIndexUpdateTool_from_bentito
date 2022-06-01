Reporting tool, generates HTML reports for operators updating from one EUS OCP index to another.

Install: 
Python 3.x

execute:

`pip install dominate`

Run:

`python3 crossIndexUpdateTool.py [-h] [--debug DEBUG] start_index target_index operator_name`

(Note: you must put an operator_name, but it's ignored for now, 
all known Red Hat operators are included in the report.)

`resource/index` contains the Red Hat Operator indexes which are
the databases with the package and bundle information.

The indexes are always changing, so if you want a completely up-to-date report,
you must download fresh copies of the indexes.