export const uploadBody = {
  type: 'object',
  properties: {
    filename: { type: 'string' },
    contentType: { type: 'string' },
  },
  required: ["filename"],
} as const;
