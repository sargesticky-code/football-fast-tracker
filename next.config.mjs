const isPages = process.env.GITHUB_ACTIONS === "true";
const repo = "football-fast-tracker";

export default {
  ...(isPages ? { output: "export" } : {}),
  trailingSlash: isPages,
  images: { unoptimized: isPages },
  basePath: isPages ? `/${repo}` : "",
  assetPrefix: isPages ? `/${repo}/` : "",
};
