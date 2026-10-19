import { createServerFn } from "@tanstack/react-start";
import { createTypesenseClient } from "./client.server";

export type Dataset = {
  id: string;
  doi: string;
  title: string;
  description: string;
  keywords: string[];
  authors: string[];
  license: string;
  publicationDate: string;
  url: string;
  data_source: string;
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
