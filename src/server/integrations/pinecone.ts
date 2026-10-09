import "server-only";
import { Pinecone } from "@pinecone-database/pinecone";
import { readIntegrationConfig } from "@/server/config";

// 仅引用已有索引；索引维度必须与运行时注入的 Embedding 实现一致。
export function createPineconeIndex() {
  const config = readIntegrationConfig("pinecone");
  const client = new Pinecone({ apiKey: config.PINECONE_API_KEY });
  return client.index({
    name: config.PINECONE_INDEX,
    ...(config.PINECONE_NAMESPACE ? { namespace: config.PINECONE_NAMESPACE } : {}),
  });
}
