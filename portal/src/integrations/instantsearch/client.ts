import TypesenseInstantSearchAdapter from "typesense-instantsearch-adapter";

type SearchConfig = {
  apiKey: string;
  node: { host: string; port: number; protocol: "http" | "https"; path?: string };
};

export function createSearchClient(config: SearchConfig) {
  return new TypesenseInstantSearchAdapter({
    server: { apiKey: config.apiKey, nodes: [config.node] },
    additionalSearchParameters: {
      query_by: "title,subtitle,description,interviewee",
      query_by_weights: "4,3,3,4",
    },
  }).searchClient;
}
