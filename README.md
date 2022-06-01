Reporting tool, generates HTML reports for operators updating from one EUS OCP index to another.

Install: 
Python 3.x

execute:

`pip install dominate`

Run:

`python3 crossIndexUpdateTool.py [-h] [--debug DEBUG] start_index target_index operator_name`

(Note: you must put an operator_name, but it's ignored for now, 
all known Red Hat operators are included in the report.)
