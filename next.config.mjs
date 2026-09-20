const isGitHubPages = process.env.GITHUB_ACTIONS === "true";
const isCloudflarePages = process.env.CF_PAGES === "1" || process.env.CF_PAGES === "true";
const isStaticExport = isGitHubPages || isCloudflarePages;
const repo = "football-fast-tracker";

export default {
  ...(isStaticExport ? { output: "export" } : {}),
  trailingSlash: isStaticExport,
  images: { unoptimized: isStaticExport },
  basePath: isGitHubPages ? `/${repo}` : "",
  assetPrefix: isGitHubPages ? `/${repo}/` : "",
};
