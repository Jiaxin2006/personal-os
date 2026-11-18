import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import fetch_paintings


class PaintingDownloadTests(unittest.TestCase):
    def test_automatic_batch_skips_known_and_unavailable_works(self):
        def metadata(met_id):
            if met_id == 3:
                raise ValueError('No public-domain image')
            return {'title': f'Painting {met_id}'}

        with tempfile.TemporaryDirectory() as directory:
            gallery = Path(directory) / 'gallery'
            images = gallery / 'paintings'
            images.mkdir(parents=True)
            bundled = Path(directory) / 'bundled.json'
            bundled.write_text(json.dumps([{'met_id': 1}]))
            manifest = gallery / 'paintings.json'
            existing = {'met_id': 2, 'file': '2.jpg'}
            manifest.write_text(json.dumps([existing]))
            (images / '2.jpg').write_bytes(b'original')

            with patch.object(fetch_paintings, 'LOCAL_GALLERY', gallery), \
                    patch.object(fetch_paintings, 'discover_paintings', return_value=range(1, 20)), \
                    patch.object(fetch_paintings, 'object_metadata', side_effect=metadata) as lookup, \
                    patch.object(fetch_paintings, 'download_image', side_effect=lambda meta, target: target.write_bytes(b'new')), \
                    patch('builtins.print'):
                self.assertTrue(fetch_paintings.add_local_paintings(None, bundled_manifest=bundled))

            expected = [existing['met_id'], *range(4, 4 + fetch_paintings.TOP_UP_COUNT)]
            self.assertEqual([entry['met_id'] for entry in json.loads(manifest.read_text())], expected)
            self.assertEqual([call.args[0] for call in lookup.call_args_list], [3, *expected[1:]])
            self.assertEqual((images / '2.jpg').read_bytes(), b'original')
