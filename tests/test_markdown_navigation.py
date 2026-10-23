import unittest

from mining_research_kernel.markdown_navigation import (
    inline_links,
    mask_comments_and_fences,
)


class MarkdownNavigationTests(unittest.TestCase):
    def titles(self, text):
        return [match[1] for match in inline_links(mask_comments_and_fences(text))]

    def test_comment_mask_preserves_unicode_offsets_and_crlf_lines(self):
        text = "前言 <!-- 隐藏\r\n[旧资料](old.csv) --> [当前](current.csv)\r\n"
        prose = mask_comments_and_fences(text)
        self.assertEqual(len(text), len(prose))
        self.assertEqual([i for i, char in enumerate(text) if char in "\r\n"],
                         [i for i, char in enumerate(prose) if char in "\r\n"])
        link = list(inline_links(prose))
        self.assertEqual(["当前"], [match[1] for match in link])
        self.assertEqual(text.index("[当前]"), link[0].start())

    def test_delimiter_precedence_keeps_visible_links(self):
        cases = (
            "<!--\n```md\n[Hidden](hidden.csv)\n-->\n[Visible](visible.csv)\n",
            "```md\n<!-- unfinished literal comment\n```\n[Visible](visible.csv)\n",
            "``example ` <!-- literal comment`` [Visible](visible.csv)\n",
            "<!-- unmatched ` --> `<!--` [Visible](visible.csv)\n",
            "Unmatched `\n```md\n<!-- literal comment\n```\n[Visible](visible.csv)\n",
            "<!-- one --><!-- two -->[Visible](visible.csv)<!-- unfinished [Hidden](hidden.csv)",
            r"\<!-- literal [Visible](visible.csv)",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(["Visible"], self.titles(text))

    def test_literal_comment_in_invalid_backtick_fence_info_is_not_an_opener(self):
        self.assertEqual(["Visible"], self.titles(
            "```example `<!--`\n[Visible](visible.csv)\n"))


if __name__ == "__main__":
    unittest.main()
