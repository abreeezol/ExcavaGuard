import "server-only";
import { Pinecone } from "@pinecone-database/pinecone";
import { readIntegrationConfig } from "@/server/config";

// 仅引用已有索引；检索过滤、向量维度、来源字段和证据 ID 契约后续实现。
export function createPineconeIndex() {
  const config = readIntegrationConfig("pinecone");
  const client = new Pinecone({ apiKey: config.PINECONE_API_KEY });
  return client.index({ name: config.PINECONE_INDEX });
}
