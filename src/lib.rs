#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UploadTarget {
    pub name: String,
    pub host: String,
    pub remote_dir: String,
}

#[derive(Debug, Default)]
pub struct UploadManager {
    targets: Vec<UploadTarget>,
}

impl UploadManager {
    pub fn new() -> Self { Self { targets: Vec::new() } }
    pub fn add_target(&mut self, name: &str, host: &str, r_dir: &str) {
        self.targets.push(UploadTarget { name: name.into(), host: host.into(), remote_dir: r_dir.into() });
    }
    pub fn target_count(&self) -> usize { self.targets.len() }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn test_upload_manager_aaa() {
        // Arrange
        let mut mgr = UploadManager::new();
        // Act
        mgr.add_target("SigmaDrop", "drop.sigmaos.org", "/uploads");
        // Assert
        assert_eq!(mgr.target_count(), 1);
    }
}
