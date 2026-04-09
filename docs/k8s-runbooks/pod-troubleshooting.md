# Pod Troubleshooting Runbook

## CrashLoopBackOff

### Symptoms
- Pod status shows `CrashLoopBackOff`
- Pod restarts count keeps increasing
- Container exits shortly after starting

### Diagnosis Steps
1. Check pod events: `kubectl describe pod <pod-name> -n <namespace>`
2. Check container logs: `kubectl logs <pod-name> -n <namespace> --previous`
3. Check if it's an OOM issue: Look for `OOMKilled` in pod events
4. Check resource limits: `kubectl get pod <pod-name> -n <namespace> -o yaml | grep -A5 resources`

### Common Causes
- Application crash on startup (missing config, DB connection failure)
- OOMKilled - container exceeds memory limits
- Liveness probe failure
- Missing environment variables or secrets
- Image compatibility issues

### Resolution
- **App crash**: Check logs for root cause, fix application code or configuration
- **OOMKilled**: Increase memory limits or optimize application memory usage
- **Probe failure**: Adjust probe timing (initialDelaySeconds, periodSeconds)
- **Missing config**: Verify ConfigMaps and Secrets exist and are mounted correctly

---

## Pod Stuck in Pending

### Symptoms
- Pod stays in `Pending` status
- No container is created

### Diagnosis Steps
1. Check pod events: `kubectl describe pod <pod-name> -n <namespace>`
2. Check node resources: `kubectl top nodes`
3. Check resource quotas: `kubectl describe resourcequota -n <namespace>`
4. Check node affinity/tolerations: `kubectl get pod <pod-name> -o yaml | grep -A10 affinity`

### Common Causes
- Insufficient CPU or memory on nodes
- ResourceQuota exceeded
- PersistentVolumeClaim not bound
- Node affinity/selector mismatch
- Taints without matching tolerations

### Resolution
- **Insufficient resources**: Scale up node pool or reduce resource requests
- **Quota exceeded**: Increase namespace quota or reduce other workloads
- **PVC not bound**: Check StorageClass, provision PV, or fix PVC spec
- **Affinity mismatch**: Adjust nodeSelector/affinity rules or add matching nodes

---

## OOMKilled

### Symptoms
- Container exits with reason `OOMKilled`
- Pod restarts with exit code 137
- `kubectl describe pod` shows `Last State: Terminated, Reason: OOMKilled`

### Diagnosis Steps
1. Check current memory usage: `kubectl top pod <pod-name> -n <namespace>`
2. Check memory limits: `kubectl get pod <pod-name> -o yaml | grep -A3 limits`
3. Check node memory: `kubectl top nodes`
4. Check for memory leaks in application logs

### Resolution
- Increase memory limits in deployment spec
- Optimize application memory usage (heap size, connection pools, caches)
- Add JVM flags for Java apps: `-XX:MaxRAMPercentage=75.0`
- Implement proper resource cleanup in application code

---

## ImagePullBackOff

### Symptoms
- Pod status shows `ImagePullBackOff` or `ErrImagePull`
- Container image cannot be pulled

### Diagnosis Steps
1. Check pod events: `kubectl describe pod <pod-name> -n <namespace>`
2. Verify image exists: `docker pull <image>`
3. Check imagePullSecrets: `kubectl get pod <pod-name> -o yaml | grep -A3 imagePullSecrets`
4. Check registry connectivity from node

### Common Causes
- Image tag doesn't exist
- Private registry authentication failure
- Network connectivity to registry
- Registry rate limiting (Docker Hub)

### Resolution
- **Wrong tag**: Fix image tag in deployment spec
- **Auth failure**: Create/update imagePullSecret with correct credentials
- **Network**: Check NetworkPolicy, firewall rules, proxy settings
- **Rate limit**: Use authenticated pulls or mirror registry
