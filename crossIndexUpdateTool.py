# Tool to check cross-index upgrade paths for operators

import sqlite3 as sql
import argparse
import operator

import htmltabletomd
from dominate import document
from dominate.tags import *
from dominate.util import raw
from packaging import version

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


def channels_across_indexes(connections, operator_name):
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
    channels_with_no_empties = list(filter(lambda x: x, channels))
    channelUpdate.common_channels = list(sum(set.intersection(*map(set, channels_with_no_empties)), ()))
    for channels_per_index in channels:
        channelUpdate.non_common_channels.append(
            set(sum(channels_per_index, ())).symmetric_difference(channelUpdate.common_channels))
    if DEBUG:
        print("channel common to all indexes", channelUpdate.common_channels)
    return channelUpdate


def get_max_ocp(connections, all_channel_updates):
    """
    loads info per channel, per index, for maxOpenShift version being set for head bundle
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


def html_generate(operators_in_all, operators_exist, channel_updates, **kwargs):
    """
    always generate HTML for output. If markdown output is desired, the html will be converted to MD later.
    """
    needs_attention_only = kwargs["needs_attention"]
    common_only = kwargs["common_only"]
    yes_no = kwargs["yes_no"]

    with document(title='Cross Index Update Report') as doc:
        h1("Cross Index Update Report")
        t = table(cls="container")
        with t:
            h = tr()
            with h:
                th(h1("Operator"))
                if yes_no == 'True':
                    th(h1("EUS Maintained from OpenShift Index " + list(INDEXES)[0] + " to " + list(INDEXES)[-1]))
                else:
                    for idx in INDEXES:
                        th(h1("OpenShift Index " + idx))
        for operator_name, operator_exists, channel_update in sorted(
                zip(operators_in_all, operators_exist, channel_updates), key=operator.itemgetter(0)):
            table_body = tbody()
            row_cells = []
            with t.add(table_body):
                table_row = tr()
                table_row.add(td(a(operator_name, id='%s' % operator_name, href='#%s' % operator_name)))
                with table_row:
                    for default, channels, heads, max_ocps, idx_non_common in zip(
                            channel_update.default_channel_per_index,
                            channel_update.channels,
                            channel_update.channel_heads,
                            channel_update.max_ocp_per_channel,
                            channel_update.non_common_channels):
                        table_data = td(_class="parentCell")
                        attention_row = True
                        yes_row = False
                        if not operator_exists:
                            if len(channels) == 0:
                                table_data.add(p("Operator not published in this index"))
                                row_cells.append(table_data)
                                continue
                            render_channel_rows(channel_update, channels, default, heads, max_ocps, operator_name,
                                                table_data)
                        elif len(channel_update.common_channels) == 0:
                            table_data.add("No common channels across range")
                            render_channel_rows(channel_update, channels, default, heads, max_ocps, operator_name,
                                                table_data)
                        else:
                            render_channel_rows(channel_update, channels, default, heads, max_ocps, operator_name,
                                                table_data)
                            attention_row = False
                            yes_row = True
                        row_cells.append(table_data)
            if needs_attention_only == 'True' and attention_row is False:
                table_body.remove(table_row)
            if common_only == 'True' and attention_row is True:
                table_body.remove(table_row)
            if yes_no == 'True':
                for cell in row_cells:
                    table_row.remove(cell)
                yes_no_data = td(_class="parentCell")
                if yes_row:
                    yes_no_data.add(p("Yes"))
                else:
                    yes_no_data.add(p("No"))
                table_row.add(yes_no_data)
        link(rel='stylesheet', href='cross_index_update_report.css')
    return doc


def generate_filename_suffix(**kwargs):
    """
    use the keyword flags to make a suffix for the filename
    """
    suffix = list(INDEXES)[0] + "-" + list(INDEXES)[-1] + "_"
    if all(value is None for value in kwargs.values()):
        # "all" makes sense in that all the flags limit which operators are shown, or hide complexity,
        # if there are none, we're reporting "all"
        suffix = "all"
    else:
        for flag, value in zip(kwargs.keys(), kwargs.values()):
            if value is not None:
                suffix += str(flag or '')
    return suffix


def html_output(operators_in_all, operators_exist, channel_updates, **kwargs):
    doc = html_generate(operators_in_all, operators_exist, channel_updates, **kwargs)
    suffix = generate_filename_suffix(**kwargs)
    with open('html_reports/cross_index_update_report_' + suffix + '.html', 'w') as f:
        f.write(doc.render())


def md_output(operators_in_all, operators_exist, channel_updates, **kwargs):
    doc = html_generate(operators_in_all, operators_exist, channel_updates, **kwargs)
    mark_down = htmltabletomd.convert_table(doc.render(), content_conversion_ind=True, all_cols_alignment="left")
    # library converting h1 to # in markdown and that won't work in the markdown table cells
    mark_down = mark_down.translate({ord(i): None for i in '#'})
    suffix = generate_filename_suffix(**kwargs)
    with open('md_reports/cross_index_update_report_' + suffix + '.md', 'w', encoding="utf-8",
              errors="xmlcharrefreplace") as f:
        f.write(mark_down)


def render_channel_rows(channel_update, channels, default, heads, max_ocps, operator_name, table_data):
    """
    helper for html_generate()
    """
    for channel, max_ocp, head in zip(channels, max_ocps, heads):
        channel = channel[0]
        color_class = set_color_class_common(channel, channel_update)
        if channel == default:
            table_data.add(p(span("CHANNEL: ", _class="small"), b(channel + ' (default)'), _class=color_class))
        else:
            table_data.add(p(span("CHANNEL: ", _class="small"), b(channel), _class=color_class))
        arrow_leader = "&ensp;&rarr; "
        head_bundle_version = head.replace(operator_name + ".", "")
        if max_ocp is not None:
            head_bundle_version += " (maxOCP = " + max_ocp + ")"
        table_data.add(p(raw(arrow_leader), span("CURRENT VERSION: ", _class="small"), head_bundle_version))


def set_color_class_common(channel, channel_update):
    """
    helper for html_generate()
    """
    if channel in channel_update.common_channels:
        color_class = "common-channel"
    else:
        color_class = "non-common-channel"
    return color_class


def get_all_operators_exist(connections, all_operators):
    all_operators_exist = []
    for operator in all_operators:
        all_operators_exist.append(operator_across_range(connections, operator))
    return all_operators_exist


def modify_common_by_maxocp(all_channel_updates):
    """if maxOCP indicates that a channel head won't allow cluster upgrade past some index,
    delete common channels accordingly"""
    for channel_update in all_channel_updates:
        # loop on indexes in maxOCP
        for idx, max_ocp_per_index, channels in zip(INDEXES.keys(), channel_update.max_ocp_per_channel,
                                                    channel_update.channels):
            for max_ocp, channel in zip(max_ocp_per_index, channels):
                if max_ocp is not None:
                    if version.parse(max_ocp.strip('"')) < version.parse(idx):
                        if channel[0] in channel_update.common_channels:
                            channel_update.common_channels.remove(channel[0])


def get_all_channel_updates(connections, all_operators):
    all_channel_updates = []

    for operator in all_operators:
        all_channel_updates.append(channels_across_indexes(connections, operator))
    get_max_ocp(connections, all_channel_updates)
    modify_common_by_maxocp(all_channel_updates)
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

    if args.output == "html":
        html_output(all_operators, all_operators_exist, all_channel_updates, needs_attention=args.needs_attention,
                    common_only=args.common_only, yes_no=args.yes_no)
    else:
        md_output(all_operators, all_operators_exist, all_channel_updates, needs_attention=args.needs_attention,
                  common_only=args.common_only, yes_no=args.yes_no)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("start_index", help="the index (OpenShift version) you are on now (4.[6,7,8,9,10])")
    parser.add_argument("target_index", help="the index (OpenShift version) you want to see move to (4.[6,7,8,9,10])")
    parser.add_argument("--debug", help="optionally print debug information")
    parser.add_argument("--needs-attention", help="optionally only output operators which need attention")
    parser.add_argument("--common-only",
                        help="optionally only output operators which have channels in common across all indexes")
    parser.add_argument("--yes-no",
                        help="optionally only output whether operators, 'Yes', have a clean path from index to index "
                             "for update, or 'No', they don't. Operators without a common channel in all indexes, or, "
                             "without an operator published in all indexes will show as 'No'")
    parser.add_argument("--output", help="choose output style, default is `html`, or choose `md` for markdown.",
                        default="html")
    args = parser.parse_args()

    main(args)
