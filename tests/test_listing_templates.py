import unittest
from mailer.templates import LISTING_LAYOUTS, build_listing_email


class ListingTemplatesTest(unittest.TestCase):
    def test_all_layouts_preserve_listing_and_unsubscribe(self):
        listing = {'UnparsedAddress': '123 Oak & Elm', 'City': 'Austin',
                   'ListPrice': '725,000', 'BedroomsTotal': 3,
                   'BathroomsTotalInteger': 2, 'LivingArea': '2100',
                   'PublicRemarks': '<script>alert(1)</script>\n\nA bright home.'}
        outputs = []
        for layout in LISTING_LAYOUTS:
            with self.subTest(layout=layout):
                subject, html = build_listing_email(listing, layout=layout,
                    photo_urls=['https://example.com/a.jpg', 'javascript:alert(1)'],
                    property_url='javascript:alert(1)')
                self.assertIn('$725,000', subject)
                self.assertIn('123 Oak &amp; Elm', html)
                self.assertIn('2,100', html)
                self.assertIn('__UNSUBSCRIBE_URL__', html)
                self.assertNotIn('<script>', html)
                self.assertNotIn('javascript:', html)
                self.assertIn('alt="Property photograph"', html)
                outputs.append(html)
        self.assertEqual(len(set(outputs)), len(LISTING_LAYOUTS))

    def test_missing_fields_and_invalid_numbers(self):
        for layout in LISTING_LAYOUTS:
            for value in (None, 'N/A', float('nan'), float('inf'), -1):
                with self.subTest(layout=layout, value=value):
                    _, html = build_listing_email({'UnparsedAddress': None,
                        'ListPrice': value, 'LivingArea': value}, layout=layout)
                    self.assertIn('Price on request', html)
                    self.assertNotIn('<img src=""', html)

    def test_collection_keeps_each_property_link_and_one_footer(self):
        _, html = build_listing_email(
            {"UnparsedAddress": "First home"}, layout="listing_collection",
            property_url="https://example.com/first",
            collection_entries=[dict(listing={"UnparsedAddress": "Second home", "ListPrice": "950000"},
                                     property_url="https://example.com/second", description="Second home details")],
        )
        self.assertIn('href="https://example.com/first"', html)
        self.assertIn('href="https://example.com/second"', html)
        self.assertIn('Second home details', html)
        self.assertIn('$950,000', html)
        self.assertEqual(html.count('__UNSUBSCRIBE_URL__'), 1)

    def test_legacy_drafts_remain_renderable(self):
        for layout in ('original', 'feature_spotlight', 'featured_highlight', 'editorial', 'photo_gallery', 'property_brief'):
            with self.subTest(layout=layout):
                _, html = build_listing_email({'UnparsedAddress': 'Saved home'}, layout=layout)
                self.assertIn('Saved home' if layout != 'original' else 'SAVED HOME', html)
                self.assertIn('__UNSUBSCRIBE_URL__', html)

    def test_unknown_layout_falls_back(self):
        self.assertEqual(build_listing_email({}, layout='unknown'), build_listing_email({}))


if __name__ == '__main__':
    unittest.main()
