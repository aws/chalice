import re

valid_mime_type = re.compile(r'^(\*|[a-zA-Z0-9._-]+)(/(\*|[a-zA-Z0-9._-]+))?$')


class AcceptableType:
    mime_type = None
    pattern = None

    def __init__(self, raw_mime_type):
        bits = raw_mime_type.split(';', 1)

        mime_type = bits[0]
        if not valid_mime_type.match(mime_type):
            raise ValueError('"%s" is not a valid mime type' % mime_type)

        self.mime_type = mime_type
        self.pattern = re.compile('^' + mime_type.replace('*', '[a-zA-Z0-9_.$#!%^*-]+') + '$')

    @staticmethod
    def parse_header(header):
        raw_mime_types = header.split(',')
        mime_types = []
        for raw_mime_type in raw_mime_types:
            try:
                mime_types.append(AcceptableType(raw_mime_type.strip()))
            except ValueError:
                pass

        return mime_types

    def matches(self, mime_type):
        return self.pattern.match(mime_type)

    def __str__(self):
        return self.__unicode__()

    def __unicode__(self):
        return self.mime_type

    def __repr__(self):
        return '<AcceptableType {0}>'.format(self)
