import openai from "openai";
import { Completion } from "openai/resources/completions";
import { TokenUsage } from "../chat_ui/ResponseMetrics";
import { getProxyBaseUrl } from "@/components/networking";

/**
 * /v1/completions -- for base/completion models that have no chat template
 * (e.g. a raw GPT-2 fine-tune). These reject /v1/chat/completions entirely
 * ("As of transformers v4.44, default chat template is no longer allowed"),
 * so Playground needs this separate, much simpler request path: a single
 * `prompt` string in, streamed `choices[0].text` out -- no messages array,
 * no tools/MCP/vector-stores/images, none of which such models support.
 */
export async function makeOpenAITextCompletionRequest(
  prompt: string,
  updateUI: (chunk: string, model?: string) => void,
  selectedModel: string,
  accessToken: string,
  tags?: string[],
  signal?: AbortSignal,
  onTimingData?: (timeToFirstToken: number) => void,
  onUsageData?: (usage: TokenUsage) => void,
  traceId?: string,
  temperature?: number,
  max_tokens?: number,
  onTotalLatency?: (latency: number) => void,
  customBaseUrl?: string,
  streamingEnabled: boolean = true,
) {
  const isLocal = process.env.NODE_ENV === "development";
  if (isLocal !== true) {
    console.log = function () {};
  }
  const proxyBaseUrl = customBaseUrl || getProxyBaseUrl();
  const headers: Record<string, string> = {};
  if (tags && tags.length > 0) {
    headers["x-litellm-tags"] = tags.join(",");
  }

  const client = new openai.OpenAI({
    apiKey: accessToken,
    baseURL: proxyBaseUrl,
    dangerouslyAllowBrowser: true,
    defaultHeaders: headers,
  });

  const applyUsage = (usage?: { completion_tokens?: number; prompt_tokens?: number; total_tokens?: number }) => {
    if (!usage || !onUsageData) return;
    onUsageData({
      completionTokens: usage.completion_tokens,
      promptTokens: usage.prompt_tokens,
      totalTokens: usage.total_tokens,
    });
  };

  try {
    const startTime = Date.now();
    let firstTokenReceived = false;

    const requestBody = {
      model: selectedModel,
      litellm_trace_id: traceId,
      prompt,
      ...(temperature !== undefined ? { temperature } : {}),
      ...(max_tokens !== undefined ? { max_tokens } : {}),
    };

    if (streamingEnabled) {
      const stream = await client.completions.create(
        { ...requestBody, stream: true, stream_options: { include_usage: true } },
        { signal },
      );
      for await (const chunk of stream as AsyncIterable<Completion & { usage?: any }>) {
        const text = chunk.choices?.[0]?.text;
        if (text) {
          if (!firstTokenReceived) {
            firstTokenReceived = true;
            if (onTimingData) onTimingData(Date.now() - startTime);
          }
          updateUI(text, chunk.model);
        }
        applyUsage((chunk as any).usage);
      }
    } else {
      const completion = await client.completions.create({ ...requestBody, stream: false }, { signal });
      updateUI(completion.choices?.[0]?.text ?? "", completion.model);
      applyUsage(completion.usage);
    }

    if (onTotalLatency) {
      onTotalLatency(Date.now() - startTime);
    }
  } catch (error) {
    throw error; // Re-throw to allow the caller to handle the error
  }
}
