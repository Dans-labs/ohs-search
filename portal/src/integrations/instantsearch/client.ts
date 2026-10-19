import TypesenseInstantSearchAdapter from "typesense-instantsearch-adapter";

type SearchConfig = {
  apiKey: string;
  node: { host: string; port: number; protocol: "http" | "https"; path?: string };
};

export function createSearchClient(config: SearchConfig) {
  return new TypesenseInstantSearchAdapter({
    server: { apiKey: config.apiKey, nodes: [config.node] },
    additionalSearchParameters: {
      query_by: "title,description",
      query_by_weights: "4,3",
    },
  }).searchClient;
}
