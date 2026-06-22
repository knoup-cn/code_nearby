// Package sample 是一个用于测试 chunker 和 analyzer 多语言支持的 Go 示例模块。
package sample

import (
	"fmt"
	"os"
)

// MAX_RETRIES 是最大重试次数。
const MAX_RETRIES = 3

// ComputeTotal 计算值的总和。
func ComputeTotal(values []int) int {
	total := 0
	for _, v := range values {
		total += v
	}
	return total
}

// unexportedHelper 是一个未导出的辅助函数。
func unexportedHelper() string {
	return "internal"
}

// Repository 表示一个数据仓库。
type Repository struct {
	// Root 是存储根路径。
	Root string
	// Kind 是仓库类型标识。
	Kind string
}

// NewRepository 创建一个新的 Repository。
func NewRepository(root string) *Repository {
	return &Repository{Root: root, Kind: "widget"}
}

// Load 根据 key 加载数据。
func (r *Repository) Load(key string) ([]byte, error) {
	data, err := os.ReadFile(r.Root + "/" + key)
	if err != nil {
		return nil, fmt.Errorf("load failed: %w", err)
	}
	return data, nil
}

// privateMethod 是未导出的方法。
func (r *Repository) privateMethod() {
	// 内部实现
}
