BEGIN;
DO $guard$
BEGIN
 IF current_database()<>'anki_study_catalog'
 OR (SELECT oid FROM pg_namespace WHERE nspname='study_restore_20261015_full_v1') IS DISTINCT FROM 18510802::oid
 OR (SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='study_restore_20261015_full_v1') IS DISTINCT FROM 'anki_study_catalog_owner'
 OR (SELECT jsonb_agg(jsonb_build_array(c.oid::bigint,c.relname,c.relkind::text,pg_get_userbyid(c.relowner),c.relfilenode::bigint) ORDER BY c.relname) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='study_restore_20261015_full_v1') IS DISTINCT FROM '[[18511071,"analyses","r","anki_study_catalog_owner",18511071],[18511077,"analyses_pkey","i","anki_study_catalog_owner",18511077],[18511198,"analysis_occurrences","r","anki_study_catalog_owner",18511198],[18511205,"analysis_occurrences_book_id_source_card_id_ordinal_key","i","anki_study_catalog_owner",18511205],[18511203,"analysis_occurrences_pkey","i","anki_study_catalog_owner",18511203],[18511112,"analysis_senses","r","anki_study_catalog_owner",18511112],[18511117,"analysis_senses_pkey","i","anki_study_catalog_owner",18511117],[18511094,"analysis_words","i","anki_study_catalog_owner",18511094],[18511054,"archive_rows","r","anki_study_catalog_owner",18511054],[18511059,"archive_rows_pkey","i","anki_study_catalog_owner",18511059],[18511031,"archive_tables","r","anki_study_catalog_owner",18511031],[18511037,"archive_tables_pkey","i","anki_study_catalog_owner",18511037],[18510849,"book_sources","r","anki_study_catalog_owner",18510849],[18510854,"book_sources_pkey","i","anki_study_catalog_owner",18510854],[18510829,"books","r","anki_study_catalog_owner",18510829],[18510834,"books_pkey","i","anki_study_catalog_owner",18510834],[18511228,"chunks","r","anki_study_catalog_owner",18511228],[18511233,"chunks_pkey","i","anki_study_catalog_owner",18511233],[18510964,"component_revisions","r","anki_study_catalog_owner",18510964],[18510963,"component_revisions_id_seq","S","anki_study_catalog_owner",18510963],[18510969,"component_revisions_pkey","i","anki_study_catalog_owner",18510969],[18510921,"components","r","anki_study_catalog_owner",18510921],[18510926,"components_pkey","i","anki_study_catalog_owner",18510926],[18510928,"components_word_id_name_original_id_key","i","anki_study_catalog_owner",18510928],[18511176,"decisions","r","anki_study_catalog_owner",18511176],[18511181,"decisions_pkey","i","anki_study_catalog_owner",18511181],[18511095,"dictionary_senses","r","anki_study_catalog_owner",18511095],[18511100,"dictionary_senses_pkey","i","anki_study_catalog_owner",18511100],[18511246,"events","r","anki_study_catalog_owner",18511246],[18511245,"events_id_seq","S","anki_study_catalog_owner",18511245],[18511251,"events_pkey","i","anki_study_catalog_owner",18511251],[18510962,"fields_component","i","anki_study_catalog_owner",18510962],[18510803,"metadata","r","anki_study_catalog_owner",18510803],[18510808,"metadata_pkey","i","anki_study_catalog_owner",18510808],[18510986,"native_cards","r","anki_study_catalog_owner",18510986],[18510991,"native_cards_pkey","i","anki_study_catalog_owner",18510991],[18510945,"note_fields","r","anki_study_catalog_owner",18510945],[18510950,"note_fields_pkey","i","anki_study_catalog_owner",18510950],[18510920,"note_words","i","anki_study_catalog_owner",18510920],[18510893,"notes","r","anki_study_catalog_owner",18510893],[18510901,"notes_book_id_guid_key","i","anki_study_catalog_owner",18510901],[18510903,"notes_book_id_ordinal_key","i","anki_study_catalog_owner",18510903],[18510899,"notes_pkey","i","anki_study_catalog_owner",18510899],[18510810,"objects","r","anki_study_catalog_owner",18510810],[18510818,"objects_pkey","i","anki_study_catalog_owner",18510818],[18511227,"occurrence_decisions","i","anki_study_catalog_owner",18511227],[18511008,"resource_aliases","r","anki_study_catalog_owner",18511008],[18511013,"resource_aliases_pkey","i","anki_study_catalog_owner",18511013],[18511030,"resource_content","i","anki_study_catalog_owner",18511030],[18511151,"sentence_sources","i","anki_study_catalog_owner",18511151],[18511129,"sentences","r","anki_study_catalog_owner",18511129],[18511134,"sentences_pkey","i","anki_study_catalog_owner",18511134],[18510836,"sources","r","anki_study_catalog_owner",18510836],[18510842,"sources_pkey","i","anki_study_catalog_owner",18510842],[18511175,"token_words","i","anki_study_catalog_owner",18511175],[18511152,"tokens","r","anki_study_catalog_owner",18511152],[18511158,"tokens_pkey","i","anki_study_catalog_owner",18511158],[18510876,"units","r","anki_study_catalog_owner",18510876],[18510881,"units_pkey","i","anki_study_catalog_owner",18510881],[18510820,"words","r","anki_study_catalog_owner",18510820],[18510827,"words_language_surface_key","i","anki_study_catalog_owner",18510827],[18510825,"words_pkey","i","anki_study_catalog_owner",18510825]]'::jsonb
 THEN RAISE EXCEPTION 'restore cleanup target identity changed'; END IF;
END;
$guard$;
DROP TABLE "study_restore_20261015_full_v1"."analyses",
  "study_restore_20261015_full_v1"."analysis_occurrences",
  "study_restore_20261015_full_v1"."analysis_senses",
  "study_restore_20261015_full_v1"."archive_rows",
  "study_restore_20261015_full_v1"."archive_tables",
  "study_restore_20261015_full_v1"."book_sources",
  "study_restore_20261015_full_v1"."books",
  "study_restore_20261015_full_v1"."chunks",
  "study_restore_20261015_full_v1"."component_revisions",
  "study_restore_20261015_full_v1"."components",
  "study_restore_20261015_full_v1"."decisions",
  "study_restore_20261015_full_v1"."dictionary_senses",
  "study_restore_20261015_full_v1"."events",
  "study_restore_20261015_full_v1"."metadata",
  "study_restore_20261015_full_v1"."native_cards",
  "study_restore_20261015_full_v1"."note_fields",
  "study_restore_20261015_full_v1"."notes",
  "study_restore_20261015_full_v1"."objects",
  "study_restore_20261015_full_v1"."resource_aliases",
  "study_restore_20261015_full_v1"."sentences",
  "study_restore_20261015_full_v1"."sources",
  "study_restore_20261015_full_v1"."tokens",
  "study_restore_20261015_full_v1"."units",
  "study_restore_20261015_full_v1"."words" RESTRICT;
DROP SCHEMA "study_restore_20261015_full_v1" RESTRICT;
COMMIT;
