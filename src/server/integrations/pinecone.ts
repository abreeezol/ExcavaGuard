import "server-only";
import { Pinecone } from "@pinecone-database/pinecone";
import { readIntegrationConfig } from "@/server/config";

// 仅引用已有的 integrated embedding 索引；创建与批量导入由离线工具完成。
export function createPineconeIndex() {
  const config = readIntegrationConfig("pinecone");
  const client = new Pinecone({ apiKey: config.PINECONE_API_KEY });
  return client.index({
    name: config.PINECONE_INDEX,
    ...(config.PINECONE_NAMESPACE ? { namespace: config.PINECONE_NAMESPACE } : {}),
  });
}
