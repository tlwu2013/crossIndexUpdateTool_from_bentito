# Tool to check cross-index upgrade paths for operators

import sqlite3 as sql
import argparse
from dominate import document
from dominate.tags import *
from dominate.util import raw

INDEX_4_6 = "resource/index/index.db.4.6.redhat-operators"
INDEX_4_7 = "resource/index/index.db.4.7.redhat-operators"
INDEX_4_8 = "resource/index/index.db.4.8.redhat-operators"
INDEX_4_9 = "resource/index/index.db.4.9.redhat-operators"
INDEX_4_10 = "resource/index/index.db.4.10.redhat-operators"
INDEXES = {"4.6": INDEX_4_6, "4.7": INDEX_4_7, "4.8": INDEX_4_8, "4.9": INDEX_4_9, "4.10": INDEX_4_10}
DEBUG = False


def operator_across_range(connections, operator_name):
    args = (operator_name,)
    query = "SELECT p.name FROM package p WHERE name = ?"
    if DEBUG:
        print("operator:", operator_name)
    for index_name, _ in INDEXES.items():
        try:
            cursor = connections[index_name].cursor()
            cursor.execute(query, args)
            rows = cursor.fetchall()
            if len(rows) == 0:
                return False
            for row in rows:
                if DEBUG:
                    print("in index", index_name, row[0], "exists.")
        except sql.Error as err:
            print('Sql error: %s' % (' '.join(err.args)))
            print("Exception class is: ", err.__class__)
            return False
    return True


def get_default_channels_and_heads(rows):
    channel_only = []
    default_channels = []
    heads = []
    for row in rows:
        channel_only.append((row[0],))
        default_channels.append(row[1])
        heads.append(row[2])
    return channel_only, default_channels, heads


def channels_across_range(connections, operator_name):
    """
    Determine common channels that exist across all indexes
    :param connections: a dict of connections to the sqlite databases
    :param operator_name: operator to check
    :return: list of channels, default channels and operator bundle heads in common for all indexes
    """
    args = (operator_name,)
    query = """
    SELECT c.name, p.default_channel, c.head_operatorbundle_name
    FROM package p, channel c 
    JOIN package on p.name = c.package_name
    WHERE package_name = ? 
    GROUP BY c.name;"""
    if DEBUG:
        print("operator:", operator_name)
    channels = []
    default_channel_per_index = []
    channel_heads = []
    for index_name, _ in INDEXES.items():
        try:
            cursor = connections[index_name].cursor()
            cursor.execute(query, args)
            rows = cursor.fetchall()
            rows, default_channels, heads = get_default_channels_and_heads(rows)
            if DEBUG:
                print("in index", index_name, "found channels, defaults and head bundle info:", rows)
            channels.append(rows)
            if len(default_channels) > 0:
                default_channel_per_index.append(default_channels[0])
            else:
                default_channel_per_index.append(None)
            channel_heads.append(heads)
        except sql.Error as err:
            print('Sql error: %s' % (' '.join(err.args)))
            print("Exception class is: ", err.__class__)
            return []
    channels_in_all = list(sum(set.intersection(*map(set, channels)), ()))
    if DEBUG:
        print("channel common to all indexes", channels_in_all)
    return channels_in_all, default_channel_per_index, channel_heads


# TODO remove? I think no-touch EUS-EUS doesn't actually need logic like this?
def versions_across_range(connections, operator_name):
    """
     Determine common versions that exist across all indexes
     :param connections: a dict of connections to the sqlite databases
     :param operator_name: operator to check
     :return: list of versions in common for all indexes
     """
    args = (operator_name,)
    query = """SELECT
        b.name 
    FROM channel_entry e
    LEFT JOIN
        channel_entry r ON r.entry_id = e.replaces
    LEFT JOIN
        operatorbundle b ON e.operatorbundle_name = b.name
    LEFT JOIN
        channel c ON e.package_name = c.package_name AND e.channel_name = c.name
    LEFT JOIN
        package p on c.package_name = p.name
    WHERE p.name = ?;"""
    if DEBUG:
        print("operator:", operator_name)
    versions = []
    for index_name, _ in INDEXES.items():
        try:
            cursor = connections[index_name].cursor()
            cursor.execute(query, args)
            rows = cursor.fetchall()
            if DEBUG:
                print("in index", index_name, "found versions", rows)
            versions.append(rows)
        except sql.Error as err:
            print('Sql error: %s' % (' '.join(err.args)))
            print("Exception class is: ", err.__class__)
            return []
    versions_in_all = list(set.intersection(*map(set, versions)))
    if DEBUG:
        print("versions common to all indexes", versions_in_all)
    return versions_in_all


def get_all_operators(connections):
    operators = []
    query = """SELECT
        p.name
    FROM 
        package p;"""
    for index_name, _ in INDEXES.items():
        try:
            cursor = connections[index_name].cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            if DEBUG:
                print("in index", index_name, "found versions", rows)
            operators.append(sum(rows, ()))
        except sql.Error as err:
            print('Sql error: %s' % (' '.join(err.args)))
            print("Exception class is: ", err.__class__)
            return []
    return set().union(*operators)


def trim_indexes(start_index, target_index):
    """
    reduce the list of indexes as requested
    :param start_index: starting index
    :param target_index: target index
    :return: (none, we alter the global INDEXES value for convenience in simple script)
    """
    trimmed_index = {}
    adding = False
    for idx_name, index in INDEXES.items():
        if idx_name == start_index or adding:
            trimmed_index[idx_name] = INDEXES[idx_name]
            adding = True
            if idx_name == target_index:
                adding = False
    return trimmed_index


def html_output(operators_in_all, operators_exist, channels_in_all, heads_in_all, defaults_per_index):
    with document(title='Cross Index Update Report') as doc:
        h1("Cross Index Update Report")
        t = table(cls="container")
        with t.add(thead()):
            h = tr()
            with h:
                th(h1("Operator"))
                for idx in INDEXES:
                    th(h1(idx))
        for operator_name, operator_exists, channels, heads, default_per_index in zip(operators_in_all, operators_exist,
                                                                                      channels_in_all,
                                                                                      heads_in_all, defaults_per_index):
            with t.add(tbody()):
                l = tr()
                l.add(td(operator_name))
                with l:
                    for _, default, head in zip(INDEXES, default_per_index, heads):
                        t = td()
                        if not operator_exists:
                            t.add(p("Operator does not exist in every index"))
                        elif len(channels) == 0:
                            t.add(p("No common channels across range"))
                        else:
                            for channel in channels:
                                if channel == default:
                                    t.add(p(channel + ' (default)'))
                                else:
                                    t.add(p(channel))
                                t.add(p(raw("&ensp;&rarr; " + head[0].replace(operator_name + ".", ""))))
    with doc.head:
        link(rel='stylesheet', href='cross_index_update_report.css')

    with open('cross_index_update_report.html', 'w') as f:
        f.write(doc.render())


def get_all_operators_exist(connections, all_operators):
    all_operators_exist = []
    for operator in all_operators:
        all_operators_exist.append(operator_across_range(connections, operator))
    return all_operators_exist


def get_all_channels(connections, all_operators):
    all_channels = []
    all_defaults = []
    all_heads = []
    for operator in all_operators:
        common_channels, default_channel_per_index, heads = channels_across_range(connections, operator)
        all_channels.append(common_channels)
        all_defaults.append(default_channel_per_index)
        all_heads.append(heads)
    return all_channels, all_defaults, all_heads


def main(args):
    global INDEXES
    global DEBUG
    start_idx = args.start_index
    target_idx = args.target_index
    operator_name = args.operator_name
    if args.debug:
        print("Debug printing turned on")
        DEBUG = True
    else:
        DEBUG = False

    INDEXES = trim_indexes(start_idx, target_idx)

    # a dict of sqlite connection objects to pass around
    connections = {}
    for idx_name, index in INDEXES.items():
        connections[idx_name] = sql.connect(index)

    all_operators = get_all_operators(connections)
    all_operators_exist = get_all_operators_exist(connections, all_operators)
    all_channels, default_channel_per_index, all_heads = get_all_channels(connections, all_operators)

    # TODO max_ocp_check()
    """
    check a list of operator_name_versions to make sure they don't violate max.ocp along the way of OCP updates
    """
    # TODO deprecation_check()
    """
    check a list of operator_name_versions to make sure they aren't deprecated
    """
    # TODO version_in_channel_check()
    """
    check to make sure a given version is in the same channel along the index update progression, or return the channel
    changes that are manually needed to be made
    """
    # TODO can_update_version_to_workable()
    """
    given two versions can you update from one to the other, even if a manual channel change is needed
    """

    html_output(all_operators, all_operators_exist, all_channels, all_heads, default_channel_per_index)
    # cli_output(operators, channels, versions)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("start_index", help="the index (OpenShift version) you are on now (4.[6,7,8,9,10])")
    parser.add_argument("target_index", help="the index (OpenShift version) you want to see move to (4.[6,7,8,9,10])")
    parser.add_argument("operator_name", help="name of operator you want to see cross-index update information about")
    parser.add_argument("--debug", help="optionally print debug information")
    args = parser.parse_args()

    main(args)
