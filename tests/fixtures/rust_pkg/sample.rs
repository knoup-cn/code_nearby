//! Sample module for chunker and analyzer multi-language tests (Rust).

use std::fs;
use std::io;

/// 最大重试次数。
const MAX_RETRIES: u32 = 3;

/// 计算值的总和。
pub fn compute_total(values: &[i32]) -> i32 {
    fn doubled(v: i32) -> i32 {
        v * 2
    }
    values.iter().map(|&v| doubled(v)).sum()
}

/// 异步获取远程数据。
pub async fn fetch_remote(url: &str) -> Result<String, reqwest::Error> {
    let response = reqwest::get(url).await?;
    response.text().await
}

fn private_helper() -> String {
    "internal".to_string()
}

/// 数据仓库结构体。
#[derive(Debug)]
pub struct Repository {
    /// 存储根路径。
    pub root: String,
    /// 仓库类型。
    pub kind: String,
}

impl Repository {
    /// 创建新的 Repository。
    pub fn new(root: String) -> Self {
        Self {
            root,
            kind: "widget".to_string(),
        }
    }

    /// 根据 key 加载数据。
    pub fn load(&self, key: &str) -> io::Result<Vec<u8>> {
        fs::read(format!("{}/{}", self.root, key))
    }

    fn private_method(&self) -> String {
        String::new()
    }
}
