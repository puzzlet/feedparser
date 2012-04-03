"""A parser for SGML, using the derived class as a static DTD."""

# XXX This only supports those SGML features used by HTML.

# XXX There should be a way to distinguish between PCDATA (parsed
# character data -- the normal case), RCDATA (replaceable character
# data -- only char and entity references and end tags are special)
# and CDATA (character data -- only end tags are special).  RCDATA is
# not supported at all.

import html.parser
import re

__all__ = ["SGMLParser", "SGMLParseError"]

# Regular expressions used for parsing

incomplete = re.compile('&([a-zA-Z][a-zA-Z0-9]*|#[0-9]*)?|'
                           '<([a-zA-Z][^<>]*|'
                              '/([a-zA-Z][^<>]*)?|'
                              '![^<>]*)?')

entityref = re.compile('&([a-zA-Z][-.a-zA-Z0-9]*)[^a-zA-Z0-9]')
charref = re.compile('&#(\d+|x[0-9a-fA-F]+);')

starttagopen = re.compile('<[>a-zA-Z]')
shorttagopen = re.compile('<[a-zA-Z][-.a-zA-Z0-9]*/')
shorttag = re.compile('<([a-zA-Z][-.a-zA-Z0-9]*)/([^/]*)/')
tagfind = re.compile('[a-zA-Z][-_.:a-zA-Z0-9]*')
attrfind = re.compile(
    r'\s*([a-zA-Z_][-:.a-zA-Z_0-9]*)(\s*=\s*'
    r'(\'[^\']*\'|"[^"]*"|[][\-a-zA-Z0-9./,:;+*%?!&$\(\)_#=~\'"@]*))?')


class SGMLParseError(RuntimeError):
    """Exception raised for all parse errors."""
    pass

class SGMLParser(html.parser.HTMLParser):
    # Definition of entities -- derived classes may override
    entity_or_charref = re.compile('&(?:'
      '([a-zA-Z][-.a-zA-Z0-9]*)|#([0-9]+)'
      ')(;?)')

    def __init__(self, verbose=0):
        """Initialize and reset this instance."""
        html.parser.HTMLParser.__init__(self)
        self.verbose = verbose
        self.reset()

    def reset(self):
        """Reset this instance. Loses all unprocessed data."""
        self.__starttag_text = None
        self.stack = []
        self.nomoretags = 0
        html.parser.HTMLParser.reset(self)

    def error(self, message):
        raise SGMLParseError(message)

    # Internal -- handle data as far as reasonable.  May leave state
    # and data to be processed by a subsequent call.  If 'end' is
    # true, force handling all data as if followed by EOF marker.
    def goahead(self, end):
        rawdata = self.rawdata
        i = 0
        n = len(rawdata)
        while i < n:
            if self.nomoretags:
                self.handle_data(rawdata[i:n])
                i = n
                break
            match = self.interesting.search(rawdata, i) # < or &
            if match: j = match.start()
            else: j = n
            if i < j:
                self.handle_data(rawdata[i:j])
            i = self.updatepos(i, j)
            if i == n: break
            startswith = rawdata.startswith
            if startswith('<', i):
                if starttagopen.match(rawdata, i): # < + letter
                    k = self.parse_starttag(i)
                elif startswith("</", i):
                    k = self.parse_endtag(i)
                elif startswith("<!--", i):
                    k = self.parse_comment(i)
                elif startswith("<?", i):
                    k = self.parse_pi(i)
                elif startswith("<!", i):
                    k = self.parse_declaration(i)
                elif (i + 1) < n:
                    self.handle_data("<")
                    k = i + 1
                else:
                    break
                if k < 0:
                    if end:
                        pass #self.error("EOF in middle of construct")
                    break
                i = self.updatepos(i, k)
                continue
            elif startswith('&', i):
                match = charref.match(rawdata, i)
                if match:
                    name = match.group(1)
                    self.handle_charref(name)
                    k = match.end()
                    if not startswith(';', k-1):
                        k = k - 1
                    i = self.updatepos(i, k)
                    continue
                match = entityref.match(rawdata, i)
                if match:
                    name = match.group(1)
                    self.handle_entityref(name)
                    k = match.end()
                    if not startswith(';', k-1):
                        k = k - 1
                    i = self.updatepos(i, k)
                    continue
            else:
                self.error('neither < nor & ??')
            # We get here only if incomplete matches but
            # nothing else
            match = incomplete.match(rawdata, i)
            if not match:
                self.handle_data(rawdata[i])
                i = i+1
                continue
            j = match.end(0)
            if j == n:
                break # Really incomplete
            self.handle_data(rawdata[i:j])
            i = j
        # end while
        if end and i < n:
            self.handle_data(rawdata[i:n])
            i = self.updatepos(i, n)
        self.rawdata = rawdata[i:]
        # XXX if end: check for empty stack

    # Internal -- handle starttag, return length or -1 if not terminated
    def parse_starttag(self, i):
        self.__starttag_text = None
        start_pos = i
        rawdata = self.rawdata
        if shorttagopen.match(rawdata, i):
            # SGML shorthand: <tag/data/ == <tag>data</tag>
            # XXX Can data contain &... (entity or char refs)?
            # XXX Can data contain < or > (tag characters)?
            # XXX Can there be whitespace before the first /?
            match = shorttag.match(rawdata, i)
            if not match:
                return -1
            tag, data = match.group(1, 2)
            self.__starttag_text = '<%s/' % tag
            tag = tag.lower()
            k = match.end(0)
            self.finish_shorttag(tag, data)
            self.__starttag_text = rawdata[start_pos:match.end(1) + 1]
            return k
        # XXX The following should skip matching quotes (' or ")
        # As a shortcut way to exit, this isn't so bad, but shouldn't
        # be used to locate the actual end of the start tag since the
        # < or > characters may be embedded in an attribute value.
        match = endbracket.search(rawdata, i+1)
        if not match:
            return -1
        j = match.start(0)
        # Now parse the data between i+1 and j into a tag and attrs
        attrs = []
        if rawdata[i:i+2] == '<>':
            # SGML shorthand: <> == <last open tag seen>
            k = j
            tag = self.lasttag
        else:
            match = tagfind.match(rawdata, i+1)
            if not match:
                self.error('unexpected call to parse_starttag')
            k = match.end(0)
            tag = rawdata[i+1:k].lower()
            self.lasttag = tag
        while k < j:
            match = attrfind.match(rawdata, k)
            if not match:
                break
            attrname, rest, attrvalue = match.group(1, 2, 3)
            if not rest:
                attrvalue = attrname
            elif (attrvalue[:1] == "'" == attrvalue[-1:] or \
                    attrvalue[:1] == '"' == attrvalue[-1:]):
                attrvalue = attrvalue[1:-1]
                attrvalue = self.entity_or_charref.sub(
                    self._convert_ref, attrvalue)
            attrs.append((attrname.lower(), attrvalue))
            k = match.end(0)
        if rawdata[j] == '>':
            j = j+1
        self.__starttag_text = rawdata[start_pos:j]
        self.finish_starttag(tag, attrs)
        return j

    # Internal -- convert entity or character reference
    def _convert_ref(self, match):
        if match.group(2):
            return self.convert_charref(match.group(2)) or \
                '&#%s%s' % match.groups()[1:]
        elif match.group(3):
            return self.convert_entityref(match.group(1)) or \
                '&%s;' % match.group(1)
        else:
            return '&%s' % match.group(1)

    # Internal -- parse endtag
    def parse_endtag(self, i):
        rawdata = self.rawdata
        match = endbracket.search(rawdata, i+1)
        if not match:
            return -1
        j = match.start(0)
        tag = rawdata[i+2:j].strip().lower()
        if rawdata[j] == '>':
            j = j+1
        self.finish_endtag(tag)
        return j

    # Internal -- finish parsing of <tag/data/ (same as <tag>data</tag>)
    def finish_shorttag(self, tag, data):
        self.finish_starttag(tag, [])
        self.handle_data(data)
        self.finish_endtag(tag)

    # Internal -- finish processing of start tag
    # Return -1 for unknown tag, 0 for open-only tag, 1 for balanced tag
    def finish_starttag(self, tag, attrs):
        method = getattr(self, 'start_' + tag, None)
        if method:
            self.stack.append(tag)
            method(tag, attrs)
            return 1
        method = getattr(self, 'do_' + tag, None)
        if method:
            method(tag, attrs)
            return 0
        self.unknown_starttag(tag, attrs)
        return -1

    # Internal -- finish processing of end tag
    def finish_endtag(self, tag):
        if not tag:
            found = len(self.stack) - 1
            if found < 0:
                self.unknown_endtag(tag)
                return
        else:
            if tag not in self.stack:
                if getattr(self, 'end_' + tag, None):
                    self.report_unbalanced(tag)
                else:
                    self.unknown_endtag(tag)
                return
            found = len(self.stack)
            for i in range(found):
                if self.stack[i] == tag: found = i
        while len(self.stack) > found:
            tag = self.stack[-1]
            method = getattr(self, 'end_' + tag, self.unknown_endtag)
            method(tag)
            del self.stack[-1]

    # Example -- report an unbalanced </...> tag.
    def report_unbalanced(self, tag):
        if self.verbose:
            print('*** Unbalanced </' + tag + '>')
            print('*** Stack:', self.stack)

    def convert_charref(self, name):
        """Convert character reference, may be overridden."""
        try:
            n = int(name)
        except ValueError:
            return
        if not 0 <= n <= 127:
            return
        return chr(n)

    # Definition of entities -- derived classes may override
    entitydefs = \
            {'lt': '<', 'gt': '>', 'amp': '&', 'quot': '"', 'apos': '\''}

    def convert_entityref(self, name):
        """Convert entity references.

        As an alternative to overriding this method; one can tailor the
        results by setting up the self.entitydefs mapping appropriately.
        """
        return self.entitydefs.get(name, None)

def test(args = None):
    import sys

    if args is None:
        args = sys.argv[1:]

    if args and args[0] == '-s':
        args = args[1:]
        klass = SGMLParser
    else:
        klass = TestSGMLParser

    if args:
        file = args[0]
    else:
        file = 'test.html'

    if file == '-':
        f = sys.stdin
    else:
        try:
            f = open(file, 'r')
        except IOError as msg:
            print(file, ":", msg)
            sys.exit(1)

    data = f.read()
    if f is not sys.stdin:
        f.close()

    x = klass()
    for c in data:
        x.feed(c)
    x.close()


if __name__ == '__main__':
    test()
