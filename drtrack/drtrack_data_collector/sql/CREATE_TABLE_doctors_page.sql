CREATE OR REPLACE EXTERNAL TABLE `i-rw-sandbox.dr_track_test.test_doctors_page` (
  fac_id_unif  STRING
  , url STRING
  , type  STRING
  , department  STRING
  , page_title  STRING
  , update_datetime STRING
  , ai_version  STRING
)
OPTIONS (
  format = "CSV",
  uris = ["gs://drtrack_test/url_collect/tsv/*.tsv"],
  field_delimiter = "\t",
  quote = '',
  null_marker = "",
  allow_quoted_newlines = true,
  allow_jagged_rows = true,
  ignore_unknown_values = true,
  skip_leading_rows = 1,
  encoding = "UTF-8"
);