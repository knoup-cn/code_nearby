/**
 * Sample module for chunker and analyzer multi-language tests (JavaScript).
 */

import fs from 'fs';
import path from 'path';

const MAX_RETRIES = 3;

/**
 * Compute total of values.
 * @param {number[]} values
 * @returns {number}
 */
export function computeTotal(values) {
  const doubled = (v) => v * 2;
  return values.reduce((sum, v) => sum + doubled(v), 0);
}

/**
 * Fetch remote data.
 * @param {string} url
 * @returns {Promise<string>}
 */
export async function fetchRemote(url) {
  const response = await fetch(url);
  return response.text();
}

function _privateHelper() {
  return 'internal';
}

/**
 * Repository class.
 */
export class Repository {
  /** @type {string} */
  kind = 'widget';

  /**
   * @param {string} root
   */
  constructor(root) {
    this.root = root;
  }

  /**
   * @returns {string}
   */
  get name() {
    return this.root;
  }

  /**
   * Load data by key.
   * @param {string} key
   * @returns {Promise<Buffer>}
   */
  async load(key) {
    const data = await fs.readFile(`${this.root}/${key}`);
    return data;
  }

  _privateMethod() {
    return '';
  }
}
