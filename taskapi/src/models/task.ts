export const taskBody = {
  type: 'object',
  properties: {
    gcsPath: { type: 'string' },
  },
  required: ["gcsPath"],
} as const;
