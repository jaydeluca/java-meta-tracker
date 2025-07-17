import unittest
import datetime
from metadata_project import parse_and_extract_metrics, get_dates_in_range, fetch_yaml_content

class TestMetadataProject(unittest.TestCase):

    def test_get_dates_in_range(self):
        start_date_str = "2025-03-01"
        end_date = datetime.date(2025, 3, 3)
        dates = get_dates_in_range(start_date_str, end_date)
        self.assertEqual(len(dates), 3)
        self.assertEqual(dates[0], datetime.date(2025, 3, 1))
        self.assertEqual(dates[1], datetime.date(2025, 3, 2))
        self.assertEqual(dates[2], datetime.date(2025, 3, 3))

        # Test with start date same as end date
        start_date_str = "2025-03-05"
        end_date = datetime.date(2025, 3, 5)
        dates = get_dates_in_range(start_date_str, end_date)
        self.assertEqual(len(dates), 1)
        self.assertEqual(dates[0], datetime.date(2025, 3, 5))

    def test_parse_and_extract_metrics(self):
        sample_yaml_content = """
        libraries:
          - name: Library A
            description: This is a description.
            target_version:
              javaagent: 1.0.0
              library: 2.0.0
            telemetry: true
          - name: Library B
            target_version:
              javaagent: 1.1.0
            telemetry: false
          - name: Library C
            description: Another description.
            target_version:
              library: 2.1.0
          - name: Library D
            # No description, no target_version, no telemetry
          - name: Library E
            description: Yet another description.
            telemetry: {}
        """

        metrics = parse_and_extract_metrics(sample_yaml_content)

        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["total_libraries"], 5)
        self.assertEqual(metrics["libraries_with_description"], 3)
        self.assertEqual(metrics["libraries_with_javaagent_target_version"], 2)
        self.assertEqual(metrics["libraries_with_library_target_version"], 2)
        self.assertEqual(metrics["libraries_with_telemetry"], 2)

    def test_parse_empty_yaml(self):
        metrics = parse_and_extract_metrics("libraries: []")
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["total_libraries"], 0)
        self.assertEqual(metrics["libraries_with_description"], 0)
        self.assertEqual(metrics["libraries_with_javaagent_target_version"], 0)
        self.assertEqual(metrics["libraries_with_library_target_version"], 0)
        self.assertEqual(metrics["libraries_with_telemetry"], 0)

    def test_parse_invalid_yaml(self):
        metrics = parse_and_extract_metrics("invalid: - yaml")
        self.assertIsNone(metrics)

    def test_parse_no_libraries_key(self):
        metrics = parse_and_extract_metrics("other_key: value")
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["total_libraries"], 0)

    def test_telemetry_empty_dict(self):
        sample_yaml = """
        libraries:
          - name: TestLib
            telemetry: {}
        """
        metrics = parse_and_extract_metrics(sample_yaml)
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["libraries_with_telemetry"], 1)


if __name__ == '__main__':
    unittest.main()