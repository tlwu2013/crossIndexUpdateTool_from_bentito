# Reporting tool, generates HTML reports for operators updating from one EUS OCP index to another.

### Install: 

Python 3.x (if not already installed)

### Execute:

`pip install dominate`

### Run:

`python3 crossIndexUpdateTool.py [-h] [--debug DEBUG] [--needs-attention True|False] start_index target_index`

#### For instance:

    `python3 crossIndexUpdateTool.py 4.8 4.10`

will run a report for moving from version of OpenShift 4.8 to 4.10

    `python3 crossIndexUpdateTool.py 4.8 4.10 --needs-attention True`

will run a report for moving from version of OpenShift 4.8 to 4.10 showing only the operators that would be problem for such an upgrade.

---
In the repo, `resource/index` contains the Red Hat Operator indexes which are
the databases with the package and bundle information.

The indexes are always changing, so if you want a completely up-to-date report,
you must download fresh copies of the indexes.

Note: `DeprecationWarning: distutils Version classes are deprecated` can safely be ignored. 