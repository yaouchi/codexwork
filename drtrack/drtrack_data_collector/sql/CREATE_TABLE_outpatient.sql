CREATE OR REPLACE EXTERNAL TABLE `i-rw-sandbox.dr_track_test.test_doctors_outpatient` (
    fac_id_unif STRING
    , fac_nm STRING
    , department STRING
    , day_of_week STRING
    , first_followup_visit STRING
    , doctors_name STRING
    , position STRING
    , charge_week STRING
    , charge_date STRING
    , specialty STRING
    , update_date STRING
    , url_single_table STRING
    , output_datetime STRING
    , ai_version STRING
)
OPTIONS (
  format = "CSV",
  uris = ["gs://drtrack_test/outpatient/tsv/*.tsv"],
  field_delimiter = "\t",
  quote = '',
  null_marker = "",
  allow_quoted_newlines = true,
  allow_jagged_rows = true,
  ignore_unknown_values = true,
  skip_leading_rows = 1,
  encoding = "UTF-8"
);