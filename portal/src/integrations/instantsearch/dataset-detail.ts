import { createServerFn } from "@tanstack/react-start";
import { createTypesenseClient } from "./client.server";

export type Dataset = {
  // --- Dataverse (always present)
  id: string;
  doi: string; // without "doi:" prefix
  dataset_name: string;
  dataset_url?: string; // https://doi.org/<doi>
  dataset_citation?: string;
  file_id: string;
  file_checksum: string;
  published_at: number; // unix seconds
  published_year: number;

  // --- descriptive
  title: string;
  subtitle?: string;
  description?: string;

  // --- people
  interviewee?: string;
  interviewee_affiliations?: string[];
  interviewer?: string[];
  interviewer_affiliations?: string[];
  interpreter?: string[];
  interpreter_affiliations?: string[];
  others?: string[];
  others_affiliations?: string[];
  recorded_by?: string[];
  recorded_by_affiliation?: string[];
  recorded_by_consent?: string[];
  authors?: string[];
  author_affiliations?: string[];
  author_orcids?: string[];

  // --- interview
  interview_location?: string[];
  interview_location_uri?: string[];
  interview_location_geo?: [number, number][]; // [lat, lon]
  interview_date?: number; // unix seconds (UTC)
  interview_date_end?: number;
  interview_year?: number;
  language_interview?: string[];
  language_interview_code?: string[];
  recording_format?: string[];
  recording_equipment?: string;
  transcript_machine?: string;

  // --- subject
  subject_keywords?: string[]; // all keywords merged
  subject_keywords_aat?: string[];
  subject_keywords_wikidata?: string[];
  subject_keywords_freetext?: string[];
  subject_keyword_uri?: string[];
  subject_locations?: string[];
  subject_location_uri?: string[];
  subject_locations_geo?: [number, number][]; // [lat, lon]
  subject_year_start?: number;
  subject_year_end?: number;

  // --- relations
  audience?: string[];
  audience_uri?: string[];
  collections?: string[];
  collections_uri?: string[];
  relation_type?: string[];
  relation_item?: string[];
  relation_reference?: string[];

  // --- administrative / rights
  language_metadata?: string;
  language_metadata_code?: string;
  contact_email?: string;
  contact_name?: string;
  contact_affiliation?: string;
  depositor?: string;
  date_available?: string;
  publisher?: string;
  publisher_ror?: string;
  publisher_country?: string;
  rightsholder?: string;
  rightsholder_ror?: string;
  rightsholder_country?: string;
  licence?: string;
  licence_url?: string;
  contains_personal_data?: boolean;
  grants?: string[];
  grant_agencies?: string[];
  grant_numbers?: string[];

  // --- attached files (non-private)
  attachment_names?: string[];
  attachment_types?: string[];
  attachment_roles?: string[];
  attachment_count?: number;
  attachment_size?: number; // bytes

  // --- the complete parsed metadata file, as a JSON string
  raw?: string;
};

const normalizeDoi = (s: string) =>
  s
    .trim()
    .replace(/^https?:\/\/(dx\.)?doi\.org\//i, "")
    .replace(/^doi:/i, "")
    .replace(/`/g, ""); // backticks would break the filter

export const getDataset = createServerFn({ method: "GET" })
  .validator((doi: string) => doi)
  .handler(async ({ data }) => {
    const doi = normalizeDoi(data); // "10.17026/SS/1XSQIU"
    const client = createTypesenseClient();
    try {
      const res = await client
        .collections<Dataset>("datasets")
        .documents()
        .search({
          q: "*",
          filter_by: `doi:=\`${doi}\``, // backticks needed because of the "/"
          per_page: 1,
        });
      return { dataset: res.hits?.[0]?.document ?? null };
    } catch (err) {
      console.error("getDataset failed", err);
      return { dataset: null };
    }
  });
