"""Apply the safe Markdown renderer's ranges to GTK text buffers."""

from gi.repository import Gtk, Pango

from markdown_render import RenderedMarkdown, Span, render_markdown


def install_tags(buffer: Gtk.TextBuffer) -> None:
    """Create a private set of text styles once for each editor/viewer."""
    definitions = {
        "bold": {"weight": Pango.Weight.BOLD},
        "italic": {"style": Pango.Style.ITALIC},
        "underline": {"underline": Pango.Underline.SINGLE},
        "strikethrough": {"strikethrough": True},
        "code": {"family": "Monospace"},
        "code_block": {"family": "Monospace", "left_margin": 8},
        "quote": {"style": Pango.Style.ITALIC, "left_margin": 10},
        "link": {"underline": Pango.Underline.SINGLE},
    }
    for level, scale in enumerate((1.55, 1.4, 1.25, 1.15, 1.1, 1.05), 1):
        definitions[f"heading{level}"] = {"weight": Pango.Weight.BOLD, "scale": scale}
    for kind, properties in definitions.items():
        if buffer.get_tag_table().lookup(f"md-{kind}") is None:
            buffer.create_tag(f"md-{kind}", **properties)


def apply_spans(buffer: Gtk.TextBuffer, spans: tuple[Span, ...]) -> None:
    """Replace only renderer-owned styles without changing source text."""
    install_tags(buffer)
    start, end = buffer.get_bounds()
    buffer.get_tag_table().foreach(
        lambda tag, *_: (
            buffer.remove_tag(tag, start, end)
            if (tag.get_property("name") or "").startswith("md-")
            else None
        )
    )
    for span in spans:
        buffer.apply_tag_by_name(
            f"md-{span.kind}",
            buffer.get_iter_at_offset(span.start),
            buffer.get_iter_at_offset(span.end),
        )


def show_markdown(
    buffer: Gtk.TextBuffer, source: str, rendered: RenderedMarkdown | None = None
) -> None:
    """Fill a read-only viewer with formatted text and hidden Markdown syntax."""
    rendered = rendered or render_markdown(source)
    buffer.set_text(rendered.text)
    apply_spans(buffer, rendered.spans)


def make_view() -> Gtk.TextView:
    """Build a selectable, wrapping viewer shared by preview and history."""
    view = Gtk.TextView()
    view.set_editable(False)
    view.set_cursor_visible(False)
    view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    view.set_left_margin(5)
    view.set_right_margin(5)
    view.get_style_context().add_class("cn-content")
    return view
