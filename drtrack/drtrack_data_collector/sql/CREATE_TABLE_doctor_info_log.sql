CREATE OR REPLACE EXTERNAL TABLE `i-rw-sandbox.dr_track_test.test_doctors_info_log` (
  logtxt STRING
)
OPTIONS (
  format = "CSV",
  uris = ["gs://drtrack_test/doctor_info/log/*.log"],
  field_delimiter = "\t",
  quote = '',
  null_marker = "",
  allow_quoted_newlines = true,
  allow_jagged_rows = true,
  ignore_unknown_values = true,
  skip_leading_rows = 0,
  encoding = "UTF-8"
);