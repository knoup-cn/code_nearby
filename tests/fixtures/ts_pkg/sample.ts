/**
 * Sample module for chunker and analyzer multi-language tests (TypeScript).
 */

import fs from 'fs';
import path from 'path';

const MAX_RETRIES = 3;

/**
 * Compute total of values.
 */
export function computeTotal(values: number[]): number {
  const doubled = (v: number): number => v * 2;
  return values.reduce((sum, v) => sum + doubled(v), 0);
}

/**
 * Fetch remote data.
 */
export async function fetchRemote(url: string): Promise<string> {
  const response = await fetch(url);
  return response.text();
}

function _privateHelper(): string {
  return 'internal';
}

/**
 * Repository class with generic type.
 */
export class Repository<T> {
  kind: string = 'widget';

  constructor(public root: string) {}

  get name(): string {
    return this.root;
  }

  /**
   * Load data by key.
   */
  async load(key: string): Promise<Buffer> {
    const data = await fs.readFile(`${this.root}/${key}`);
    return data;
  }

  private privateMethod(): string {
    return '';
  }
}
