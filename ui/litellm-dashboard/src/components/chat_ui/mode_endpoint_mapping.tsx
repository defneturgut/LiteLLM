// litellmMapping.ts

// Define an enum for the modes as returned in model_info
export enum ModelMode {
  AUDIO_SPEECH = "audio_speech",
  AUDIO_TRANSCRIPTION = "audio_transcription",
  IMAGE_GENERATION = "image_generation",
  VIDEO_GENERATION = "video_generation",
  CHAT = "chat",
  RESPONSES = "responses",
  IMAGE_EDITS = "image_edits",
  ANTHROPIC_MESSAGES = "anthropic_messages",
  EMBEDDING = "embedding",
  // Base/completion models (no chat template, e.g. a raw GPT-2) -- model_info.mode
  // stores this as "completion" (see LiteLLM_ProxyModelTable.model_info->>'mode').
  COMPLETION = "completion",
  // add additional modes as needed
}

// Define an enum for the endpoint types your UI calls
export enum EndpointType {
  IMAGE = "image",
  VIDEO = "video",
  CHAT = "chat",
  RESPONSES = "responses",
  IMAGE_EDITS = "image_edits",
  ANTHROPIC_MESSAGES = "anthropic_messages",
  EMBEDDINGS = "embeddings",
  SPEECH = "speech",
  TRANSCRIPTION = "transcription",
  A2A_AGENTS = "a2a_agents",
  MCP = "mcp",
  REALTIME = "realtime",
  INTERACTIONS = "interactions",
  // /v1/completions -- legacy text-completion endpoint for base models
  // without a chat template (Playground previously had no way to call these;
  // it always sent /v1/chat/completions, which such models reject with
  // "As of transformers v4.44, default chat template is no longer allowed").
  COMPLETION = "completion",
}

// Create a mapping between the model mode and the corresponding endpoint type
export const litellmModeMapping: Record<ModelMode, EndpointType> = {
  [ModelMode.IMAGE_GENERATION]: EndpointType.IMAGE,
  [ModelMode.VIDEO_GENERATION]: EndpointType.VIDEO,
  [ModelMode.CHAT]: EndpointType.CHAT,
  [ModelMode.RESPONSES]: EndpointType.RESPONSES,
  [ModelMode.IMAGE_EDITS]: EndpointType.IMAGE_EDITS,
  [ModelMode.ANTHROPIC_MESSAGES]: EndpointType.ANTHROPIC_MESSAGES,
  [ModelMode.AUDIO_SPEECH]: EndpointType.SPEECH,
  [ModelMode.AUDIO_TRANSCRIPTION]: EndpointType.TRANSCRIPTION,
  [ModelMode.EMBEDDING]: EndpointType.EMBEDDINGS,
  [ModelMode.COMPLETION]: EndpointType.COMPLETION,
};

export const getEndpointType = (mode: string): EndpointType => {
  // Check if the string mode exists as a key in ModelMode enum
  if (Object.values(ModelMode).includes(mode as ModelMode)) {
    const endpointType = litellmModeMapping[mode as ModelMode];
    return endpointType;
  }

  // else default to chat
  return EndpointType.CHAT;
};
