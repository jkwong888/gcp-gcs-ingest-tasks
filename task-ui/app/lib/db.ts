// import { neon, neonConfig, Pool } from '@neondatabase/serverless';

// const connectionString = process.env.POSTGRES_URL || "";

// /* run the wsproxy sidecar to the nextjs process */
// neonConfig.wsProxy = (host) => `${host}:54330/v1`;
// neonConfig.useSecureWebSocket = false;
// neonConfig.pipelineTLS = false;
// neonConfig.pipelineConnect = false;

// const pool = new Pool({ 
//     connectionString: process.env.POSTGRES_URL,
// });
// export const sql = neon(connectionString);

// export * from '@vercel/postgres';

import { Pool, QueryResultRow } from 'pg';

const pool = new Pool({ connectionString: process.env.POSTGRES_URL });

/* from: https://github.com/vercel/storage/blob/main/packages/postgres/src/sql-template.ts */
type Primitive = string | number | boolean | undefined | null;

function sqlTemplate(
  strings: TemplateStringsArray,
  ...values: Primitive[]
): [string, Primitive[]] {
  if (!isTemplateStringsArray(strings) || !Array.isArray(values)) {
    throw new Error(
      'It looks like you tried to call `sql` as a function. Make sure to use it as a tagged template.\n' +
        "\tExample: sql`SELECT * FROM users`, not sql('SELECT * FROM users')",
    );
  }

  let result = strings[0] ?? '';

  for (let i = 1; i < strings.length; i++) {
    result += `$${i}${strings[i] ?? ''}`;
  }

  return [result, values];
}

function isTemplateStringsArray(
  strings: unknown,
): strings is TemplateStringsArray {
  return (
    Array.isArray(strings) && 'raw' in strings && Array.isArray(strings.raw)
  );
}

export async function sql<O extends QueryResultRow>(
  strings: TemplateStringsArray,
  ...values: Primitive[]
) {
  const [query, params] = sqlTemplate(strings, ...values);

  return pool.query<O>(query, params);
}

