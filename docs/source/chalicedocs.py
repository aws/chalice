# This code is based on the sphinxcontrib.youtube
# code, but with support for python3 and a few other
# changes.

import re
from docutils import nodes
from docutils.parsers.rst import directives, Directive


CONTROL_HEIGHT = 30


def get_size(d, key):
    if key not in d:
        return None
    m = re.match("(\d+)(|%|px)$", d[key])
    if not m:
        raise ValueError("invalid size %r" % d[key])
    return int(m.group(1)), m.group(2) or "px"


def css(d):
    return "; ".join(sorted("%s: %s" % kv for kv in d.items()))


class youtube(nodes.General, nodes.Element):
    pass


def visit_youtube_node(self, node):
    aspect = node["aspect"]
    width = node["width"]
    height = node["height"]

    if aspect is None:
        aspect = 16, 9

    div_style = {}
    if (height is None) and (width is not None) and (width[1] == "%"):
        div_style = {
            "padding-top": "%dpx" % CONTROL_HEIGHT,
            "padding-bottom": "%f%%" % (width[0] * aspect[1] / aspect[0]),
            "width": "%d%s" % width,
            "position": "relative",
            "margin": "0 auto 30px auto",
        }
        style = {
            "position": "absolute",
            "top": "0",
            "left": "0",
            "width": "100%",
            "height": "100%",
            "border": "0",
        }
        attrs = {
            "src": "https://www.youtube.com/embed/%s" % node["id"],
            "style": css(style),
        }
    else:
        if width is None:
            if height is None:
                width = 560, "px"
            else:
                width = height[0] * aspect[0] / aspect[1], "px"
        if height is None:
            height = width[0] * aspect[1] / aspect[0], "px"
        style = {
            "width": "%d%s" % width,
            "height": "%d%s" % (height[0] + CONTROL_HEIGHT, height[1]),
            "border": "0",
        }
        attrs = {
            "src": "https://www.youtube.com/embed/%s" % node["id"],
            "style": css(style),
        }
    attrs["allowfullscreen"] = "true"
    div_attrs = {
        "CLASS": "youtube-wrapper",
        "style": css(div_style),
    }
    self.body.append(self.starttag(node, "div", **div_attrs))
    self.body.append(self.starttag(node, "iframe", **attrs))
    self.body.append("</iframe></div>")


def depart_youtube_node(self, node):
    pass


class YouTube(Directive):
    has_content = True
    required_arguments = 1
    optional_arguments = 0
    final_argument_whitespace = False
    option_spec = {
        "width": directives.unchanged,
        "height": directives.unchanged,
        "aspect": directives.unchanged,
    }

    def run(self):
        if "aspect" in self.options:
            aspect = self.options.get("aspect")
            m = re.match("(\d+):(\d+)", aspect)
            if m is None:
                raise ValueError("invalid aspect ratio %r" % aspect)
            aspect = tuple(int(x) for x in m.groups())
        else:
            aspect = None
        width = get_size(self.options, "width")
        height = get_size(self.options, "height")
        return [
            youtube(id=self.arguments[0],
                    aspect=aspect,
                    width=width,
                    height=height)
        ]


def unsupported_visit_youtube(self, node):
    self.builder.warn('youtube: unsupported output format (node skipped)')
    raise nodes.SkipNode


_NODE_VISITORS = {
    'html': (visit_youtube_node, depart_youtube_node),
    'latex': (unsupported_visit_youtube, None),
    'man': (unsupported_visit_youtube, None),
    'texinfo': (unsupported_visit_youtube, None),
    'text': (unsupported_visit_youtube, None)
}


def setup(app):
    app.add_node(youtube, **_NODE_VISITORS)
    app.add_directive("youtube", YouTube)
