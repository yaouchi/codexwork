CREATE OR REPLACE EXTERNAL TABLE `i-rw-sandbox.dr_track_test.test_doctors_info` (
  fac_id_unif STRING,
  output_order STRING,
  department STRING,
  name STRING,
  position STRING,
  specialty STRING,
  licence STRING,
  others STRING,
  output_datetime STRING,
  ai_version STRING,
  url STRING
)
OPTIONS (
  format = "CSV",
  uris = ["gs://drtrack_test/doctor_info/tsv/*.tsv"],
  field_delimiter = "\t",
  quote = '',
  null_marker = "",
  allow_quoted_newlines = true,
  allow_jagged_rows = true,
  ignore_unknown_values = true,
  skip_leading_rows = 1,
  encoding = "UTF-8"
);