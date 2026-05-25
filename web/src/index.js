export const runtime = "litert-lm-web";

export async function createLiteRtLmEngine() {
  throw new Error(
    "LiteRT-LM web bridge is scaffolded. Wire this to official LiteRT-LM web APIs."
  );
}

if (process.argv.includes("--self-test")) {
  console.log(JSON.stringify({ runtime, status: "scaffold" }));
}
