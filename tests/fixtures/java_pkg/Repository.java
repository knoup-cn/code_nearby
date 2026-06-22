package com.example;

import java.util.List;
import java.io.IOException;

/**
 * Sample class for chunker and analyzer multi-language tests (Java).
 */
public class Repository extends BaseRepo implements Serializable {

    private static final int MAX_RETRIES = 3;

    private String root;

    /**
     * Create a new Repository.
     */
    public Repository(String root) {
        this.root = root;
    }

    /**
     * Load data by key.
     */
    public byte[] load(String key) throws IOException {
        return java.nio.file.Files.readAllBytes(
            java.nio.file.Path.of(root, key));
    }

    /**
     * Get max retries.
     */
    public static int getMaxRetries() {
        return MAX_RETRIES;
    }

    private void helper() {
        // internal helper
    }
}
