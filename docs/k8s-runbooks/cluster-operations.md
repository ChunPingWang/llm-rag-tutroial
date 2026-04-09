# Cluster Operations Runbook

## Node NotReady

### Symptoms
- `kubectl get nodes` shows one or more nodes as `NotReady`
- Pods on affected nodes may be evicted or stuck in `Terminating`

### Diagnosis Steps
1. Check node status: `kubectl describe node <node-name>`
2. Check node conditions: `kubectl get node <node-name> -o json | jq '.status.conditions'`
3. Check kubelet logs (if accessible): `journalctl -u kubelet -n 100`
4. Check system resources: `kubectl top node <node-name>`

### Common Causes
- Kubelet not running or crashed
- Network connectivity lost
- Disk pressure (node filesystem full)
- Memory pressure
- PID pressure

### Resolution
- **Kubelet crash**: SSH to node, restart kubelet: `systemctl restart kubelet`
- **Network**: Check node network configuration, CNI plugin status
- **Disk pressure**: Clean up unused images: `docker system prune` or `crictl rmi --prune`
- **Memory pressure**: Identify memory-heavy pods, add more nodes

---

## Networking Issues

### Symptoms
- Pods cannot communicate with each other
- Service DNS resolution fails
- External traffic not reaching pods

### Diagnosis Steps
1. Check DNS: `kubectl run test --rm -it --image=busybox -- nslookup kubernetes.default`
2. Check service endpoints: `kubectl get endpoints <service-name> -n <namespace>`
3. Check NetworkPolicies: `kubectl get networkpolicy -n <namespace>`
4. Check CNI plugin status: `kubectl get pods -n kube-system | grep -E 'calico|flannel|weave|cilium'`
5. Check kube-proxy: `kubectl get pods -n kube-system | grep kube-proxy`

### Common Causes
- NetworkPolicy blocking traffic
- CoreDNS not running or overloaded
- CNI plugin misconfiguration
- Service selector mismatch (no matching pods)
- kube-proxy issues

### Resolution
- **NetworkPolicy**: Review and adjust policies, use `kubectl describe networkpolicy`
- **DNS**: Restart CoreDNS: `kubectl rollout restart deployment coredns -n kube-system`
- **CNI**: Check CNI pod logs, restart if needed
- **Selector mismatch**: Verify labels on pods match service selector

---

## Certificate Expiry

### Symptoms
- API server connection failures with TLS errors
- `kubectl` commands fail with certificate errors
- Webhook calls failing

### Diagnosis Steps
1. Check cert expiry: `kubeadm certs check-expiration`
2. Check API server cert: `openssl s_client -connect <api-server>:6443 2>/dev/null | openssl x509 -noout -dates`
3. Check webhook certs if applicable

### Resolution
- Renew certificates: `kubeadm certs renew all`
- Restart control plane components after renewal
- For managed K8s (EKS/GKE/AKS): certificates are auto-managed

---

## etcd Issues

### Symptoms
- API server slow or unresponsive
- Objects not persisting
- Leader election failures

### Diagnosis Steps
1. Check etcd health: `kubectl get componentstatuses`
2. Check etcd pods: `kubectl get pods -n kube-system | grep etcd`
3. Check etcd logs: `kubectl logs -n kube-system etcd-<node> --tail=50`
4. Check disk latency on etcd nodes

### Resolution
- **Slow disk**: Move etcd to SSD storage
- **High load**: Compact and defragment etcd database
- **Member failure**: Replace failed member following etcd recovery procedures
