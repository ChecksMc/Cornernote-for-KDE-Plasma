"""Formatting renders as readable text while preserving safe Unicode ranges."""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from markdown_render import render_markdown


class MarkdownRenderTests(unittest.TestCase):
    def styled(self, rendered, kind):
        return [rendered.text[span.start:span.end]
                for span in rendered.spans if span.kind == kind]

    def source_styled(self, source, rendered, kind):
        return [source[span.start:span.end]
                for span in rendered.source_spans if span.kind == kind]

    def test_shortcut_formatting_and_heading_render_without_markers(self):
        rendered = render_markdown("# Heading\n**Bold** and *italic* and <u>underlined</u>.")
        self.assertEqual(rendered.text, "Heading\nBold and italic and underlined.")
        self.assertEqual(self.styled(rendered, "heading1"), ["Heading"])
        self.assertEqual(self.styled(rendered, "bold"), ["Bold"])
        self.assertEqual(self.styled(rendered, "italic"), ["italic"])
        self.assertEqual(self.styled(rendered, "underline"), ["underlined"])

    def test_nested_styles_and_unicode_offsets(self):
        rendered = render_markdown("😀 **Grüße _世界_**; *italic **bold***; ***both***")
        self.assertEqual(rendered.text, "😀 Grüße 世界; italic bold; both")
        self.assertEqual(self.styled(rendered, "bold"), ["Grüße 世界", "bold", "both"])
        self.assertEqual(self.styled(rendered, "italic"), ["世界", "italic bold", "both"])
        for span in rendered.spans:
            self.assertTrue(0 <= span.start < span.end <= len(rendered.text))

    def test_inline_code_and_fenced_code_remain_literal(self):
        rendered = render_markdown("`**literal**` and ``a ` b``\n```python\n# raw **code**\n```\nAfter")
        self.assertEqual(rendered.text, "**literal** and a ` b\n# raw **code**\nAfter")
        self.assertEqual(self.styled(rendered, "code"), ["**literal**", "a ` b"])
        self.assertEqual(self.styled(rendered, "code_block"), ["# raw **code**\n"])
        self.assertFalse(self.styled(rendered, "bold"))
        self.assertFalse(self.styled(rendered, "heading1"))

    def test_unclosed_fence_and_shorter_fence_are_code(self):
        rendered = render_markdown("~~~~\n**unfinished**\n~~~\n")
        self.assertEqual(rendered.text, "**unfinished**\n~~~\n")
        self.assertEqual(self.styled(rendered, "code_block"), [rendered.text])

    def test_lists_quotes_links_and_strikethrough(self):
        rendered = render_markdown("> **Quote**\n- [Site](https://example.com)\n1. ~~Done~~\n")
        self.assertEqual(rendered.text, "Quote\n• Site\n1. Done\n")
        self.assertEqual(self.styled(rendered, "quote"), ["Quote"])
        self.assertEqual(self.styled(rendered, "bold"), ["Quote"])
        self.assertEqual(self.styled(rendered, "link"), ["Site"])
        self.assertEqual(self.styled(rendered, "strikethrough"), ["Done"])

    def test_unmatched_syntax_and_arbitrary_html_stay_literal(self):
        source = "file_name_here **unfinished <script>alert(1)</script> & text"
        self.assertEqual(render_markdown(source).text, source)
        self.assertEqual(render_markdown(r"\*literal\* and \# text").text, "*literal* and # text")

    def test_empty_and_crlf_input(self):
        self.assertEqual(render_markdown("").text, "")
        self.assertEqual(render_markdown("## Title ##\r\nBody\r\n").text, "Title\nBody\n")

    def test_source_ranges_track_nested_unicode_and_removed_prefixes(self):
        source = "😀 **Grüße _世界_**\n> ## Héading **bold** ##\n- <u>Under</u>"
        rendered = render_markdown(source)
        self.assertEqual(self.source_styled(source, rendered, "bold"), ["Grüße _世界_", "bold"])
        self.assertEqual(self.source_styled(source, rendered, "italic"), ["世界"])
        self.assertEqual(self.source_styled(source, rendered, "heading2"), ["Héading **bold**"])
        self.assertEqual(self.source_styled(source, rendered, "quote"), ["## Héading **bold** ##"])
        self.assertEqual(self.source_styled(source, rendered, "underline"), ["Under"])
        for span in rendered.source_spans:
            self.assertTrue(0 <= span.start < span.end <= len(source))

    def test_source_code_ranges_and_crlf_offsets_preserve_original_text(self):
        source = "## Héading ##\r\n` code `\r\n```py\r\n**😀 literal**\r\n```\r\n**After**"
        rendered = render_markdown(source)
        self.assertEqual(self.source_styled(source, rendered, "heading2"), ["Héading"])
        self.assertEqual(self.source_styled(source, rendered, "code"), ["code"])
        self.assertEqual(self.source_styled(source, rendered, "code_block"), ["**😀 literal**\r\n"])
        self.assertEqual(self.source_styled(source, rendered, "bold"), ["After"])
        final_bold = next(span for span in rendered.source_spans if span.kind == "bold")
        self.assertEqual(final_bold.start, source.index("After"))
        self.assertEqual(final_bold.end, source.index("After") + len("After"))

    def test_unclosed_fence_source_span_excludes_opening_fence(self):
        source = "Before\n~~~\n**literal**\n"
        rendered = render_markdown(source)
        self.assertEqual(self.source_styled(source, rendered, "code_block"), ["**literal**\n"])

    def test_formatting_delimiters_inside_inline_code_do_not_close_outer_style(self):
        source = "**before `a**b` after**"
        rendered = render_markdown(source)
        self.assertEqual(rendered.text, "before a**b after")
        self.assertEqual(self.styled(rendered, "bold"), ["before a**b after"])
        self.assertEqual(self.styled(rendered, "code"), ["a**b"])
        self.assertEqual(self.source_styled(source, rendered, "bold"), ["before `a**b` after"])
        self.assertEqual(self.source_styled(source, rendered, "code"), ["a**b"])

    def test_long_unmatched_markers_stay_literal_without_quadratic_searches(self):
        started = time.monotonic()
        for source in ("[" * 40000, "*" * 40000, "*" * 40000 + "_", "<u>" * 10000):
            with self.subTest(marker=source[:4]):
                self.assertEqual(render_markdown(source).text, source)
        # The former unmatched-link pattern took several seconds for this input.
        # The large allowance tolerates loaded test hosts while catching it.
        self.assertLess(time.monotonic() - started, 2.0)


if __name__ == "__main__":
    unittest.main()
