const isPages = process.env.GITHUB_ACTIONS === "true";
const repo = "football-fast-tracker";
export default {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  basePath: isPages ? `/${repo}` : "",
  assetPrefix: isPages ? `/${repo}/` : "",
};
