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


class ChannelUpdate:
    """Hold info about each operator across indexes"""

    def __init__(self):
        self.channels = []
        self.common_channels = []
        self.default_channel_per_index = []
        self.channel_heads = []
        self.max_ocp_per_channel = []
        self.deprecated_head = []
        self.non_common_channels = []


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
    :return: list of ChannelUpdate instances for all operators in all indexes
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
    channelUpdate = ChannelUpdate()
    channels = []
    for index_name, _ in INDEXES.items():
        try:
            cursor = connections[index_name].cursor()
            cursor.execute(query, args)
            rows = cursor.fetchall()
            channels_per_index, default_channels, heads = get_default_channels_and_heads(rows)
            if DEBUG:
                print("in index", index_name, "found channels, defaults and head bundle info:", rows)
            channels.append(channels_per_index)
            if len(default_channels) > 0:
                channelUpdate.default_channel_per_index.append(default_channels[0])
            else:
                channelUpdate.default_channel_per_index.append(None)
            channelUpdate.channel_heads.append(heads)
        except sql.Error as err:
            print('Sql error: %s' % (' '.join(err.args)))
            print("Exception class is: ", err.__class__)
            return None
    channelUpdate.channels = channels
    channelUpdate.common_channels = list(sum(set.intersection(*map(set, channels)), ()))
    for channels_per_index in channels:
        channelUpdate.non_common_channels.append(
            set(sum(channels_per_index, ())).symmetric_difference(channelUpdate.common_channels))
    if DEBUG:
        print("channel common to all indexes", channelUpdate.common_channels)
    return channelUpdate


def check_max_ocp(connections, all_channel_updates):
    """
    check whether can't really update to some index due to maxOpenShift version being set for head bundle
    :param connections: dict with "INDEX_VERSION":sqlite3_connection
    :param all_channel_updates: list of ChannelUpdate instances
    :return: (mutates the field in the ChannelUpdate object instance list it is passed)
    """
    for channel_update in all_channel_updates:
        if len(channel_update.channel_heads) == 0:
            channel_update.max_ocp_per_channel.append(None)
            continue
        for channels_per_index, channel_heads_per_index, index_name in zip(channel_update.channels,
                                                                           channel_update.channel_heads,
                                                                           INDEXES.items()):
            max_ocp_per_head = []
            for channel_head in channel_heads_per_index:
                args = (channel_head,)
                query = """SELECT
                    p.value 
                FROM properties p
                WHERE p.operatorbundle_name = ? AND type = "olm.maxOpenShiftVersion";"""
                if DEBUG:
                    print("checking maxOpenshiftVersion for:", channel_head)
                try:
                    cursor = connections[index_name[0]].cursor()
                    cursor.execute(query, args)
                    row = cursor.fetchone()
                    connections[index_name[0]].commit()
                    if DEBUG:
                        print("in index", index_name, "for bundle", channel_head, "found maxOpenShiftVersion", row)
                except sql.Error as err:
                    print('Sql error: %s' % (' '.join(err.args)))
                    print("Exception class is: ", err.__class__)
                    max_ocp_per_head.append(None)
                    continue
                if row is None:
                    max_ocp_per_head.append(None)
                    continue
                max_ocp_per_head.append(row[0])
            channel_update.max_ocp_per_channel.append(max_ocp_per_head)


def check_deprecation(connections, all_channel_updates):
    """
    NOTE: found none when run on 4.8-4.10 Red Hat operators so this is debug only output, not in HTML
    check whether can't really update to some index due to deprecation being set for head bundle
    :param connections: dict with "INDEX_VERSION":sqlite3_connection
    :param all_channel_updates: list of ChannelUpdate instances
    :return: (mutates the field in the ChannelUpdate object instance list it is passed)
    """
    for channel_update in all_channel_updates:
        if len(channel_update.channel_heads) == 0:
            channel_update.deprecated_head.append(None)
            continue
        for channel_heads_per_index, index_name in zip(channel_update.channel_heads, INDEXES.items()):
            deprecated_per_head = []
            for channel_head in channel_heads_per_index:
                args = (channel_head,)
                query = """SELECT
                    d.operatorbundle_name 
                FROM deprecated d
                WHERE d.operatorbundle_name = ?;"""
                if DEBUG:
                    print("checking deprecated status for:", channel_head)
                try:
                    cursor = connections[index_name[0]].cursor()
                    cursor.execute(query, args)
                    row = cursor.fetchone()
                    if DEBUG:
                        print("in index", index_name, "found deprecated", row)
                except sql.Error as err:
                    print('Sql error: %s' % (' '.join(err.args)))
                    print("Exception class is: ", err.__class__)
                    deprecated_per_head.append(None)
                    continue
                if row is None:
                    deprecated_per_head.append(None)
                    continue
                deprecated_per_head.append(True)
            channel_update.deprecated_head.append(deprecated_per_head)


def get_all_operators(connections):
    """
    gets a list of all operators in the range of indexes, unions them to assure no dupes
    :param connections: dict with "INDEX_VERSION":sqlite3_connection
    :return: unioned set of operators in all indexes
    """
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


def html_output(operators_in_all, operators_exist, channel_updates, **kwargs):
    needs_attention_only = kwargs["needs_attention"]
    common_only = kwargs["common_only"]
    with document(title='Cross Index Update Report') as doc:
        h1("Cross Index Update Report")
        t = table(cls="container")
        with t.add(thead()):
            h = tr()
            with h:
                th(h1("Operator"))
                for idx in INDEXES:
                    th(h1("OpenShift Index " + idx))
        for operator_name, operator_exists, channel_update in zip(operators_in_all, operators_exist, channel_updates):
            table_body = tbody()
            with t.add(table_body):
                table_row = tr()
                table_row.add(td(operator_name))
                with table_row:
                    for default, channels, heads, max_ocps, idx_non_common in zip(
                            channel_update.default_channel_per_index,
                            channel_update.channels,
                            channel_update.channel_heads,
                            channel_update.max_ocp_per_channel,
                            channel_update.non_common_channels):
                        table_data = td(_class="parentCell")
                        comma_sep_non_common_channels = ", ".join(sorted(idx_non_common, key=None))
                        attention_row = True
                        if not operator_exists:
                            if len(channels) == 0:
                                table_data.add(p("Operator does not exist in every index"))
                                continue
                            for channel, max_ocp in zip(channels, max_ocps):
                                channel = channel[0]
                                if channel == default:
                                    table_data.add(p(channel + ' (default)'))
                                else:
                                    table_data.add(p(channel))
                                head_bundle_version = "&ensp;&rarr; " + heads[0].replace(operator_name + ".", "")
                                if max_ocp is not None:
                                    head_bundle_version += " (maxOCP = " + max_ocp + ")"
                                table_data.add(p(raw(head_bundle_version)))
                        elif len(channel_update.common_channels) == 0:
                            table_data.add("No common channels across range")
                            table_data.add(span(comma_sep_non_common_channels, _class="tooltip"))
                        else:
                            for channel, max_ocp, head in zip(channels, max_ocps, heads):
                                channel = channel[0]
                                if channel == default:
                                    table_data.add(p(channel + ' (default)'))
                                else:
                                    table_data.add(p(channel))
                                head_bundle_version = "&ensp;&rarr; " + head.replace(operator_name + ".", "")
                                if max_ocp is not None:
                                    head_bundle_version += " (maxOCP = " + max_ocp + ")"
                                table_data.add(p(raw(head_bundle_version)))
                            attention_row = False
            if needs_attention_only == 'True' and attention_row is False:
                table_row['style'] = 'visibility:collapse'
            if common_only == 'True' and attention_row is True:
                table_row['style'] = 'visibility:collapse'
        link(rel='stylesheet', href='cross_index_update_report.css')

    with open('cross_index_update_report.html', 'w') as f:
        f.write(doc.render())


def get_all_operators_exist(connections, all_operators):
    all_operators_exist = []
    for operator in all_operators:
        all_operators_exist.append(operator_across_range(connections, operator))
    return all_operators_exist


def get_all_channel_updates(connections, all_operators):
    all_channel_updates = []

    for operator in all_operators:
        all_channel_updates.append(channels_across_range(connections, operator))
    check_max_ocp(connections, all_channel_updates)
    check_deprecation(connections, all_channel_updates)
    return all_channel_updates


def main(args):
    global INDEXES
    global DEBUG
    start_idx = args.start_index
    target_idx = args.target_index
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
    all_channel_updates = get_all_channel_updates(connections, all_operators)

    html_output(all_operators, all_operators_exist, all_channel_updates, needs_attention=args.needs_attention,
                common_only=args.common_only)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("start_index", help="the index (OpenShift version) you are on now (4.[6,7,8,9,10])")
    parser.add_argument("target_index", help="the index (OpenShift version) you want to see move to (4.[6,7,8,9,10])")
    parser.add_argument("--debug", help="optionally print debug information")
    parser.add_argument("--needs-attention", help="optionally only output operators which need attention")
    parser.add_argument("--common-only",
                        help="optionally only output operators which have channels in common across all indexes")
    args = parser.parse_args()

    main(args)
