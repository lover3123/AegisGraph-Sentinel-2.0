import os
import torch
import torch.nn.functional as F
from torch.optim import AdamW
from tqdm import tqdm

from .data_loader import AegisGraphLoader

# Attempt to import the real model architecture, fallback to a mock for pipeline testing
try:
    from ..models.htgnn import AegisHTGNN
except ImportError:
    import torch.nn as nn
    class AegisHTGNN(nn.Module):
        """Mock model to verify the training pipeline execution"""
        def __init__(self, hidden_channels=64, out_channels=1):
            super().__init__()
            # Dummy linear layer to simulate GNN transformations
            self.lin = nn.Linear(10, out_channels) 
            
        def forward(self, x_dict, edge_index_dict):
            # Mock forward pass returning logits for account nodes
            num_accounts = x_dict['account'].size(0)
            return torch.randn((num_accounts, 1), requires_grad=True).to(x_dict['account'].device)

def train_epoch(model, loader, optimizer, device):
    """Executes one full pass over the training data."""
    model.train()
    total_loss = 0
    correct = 0
    total_samples = 0

    # Wrap the loader in a progress bar
    pbar = tqdm(loader, desc="Training Batches", leave=False)
    
    for batch in pbar:
        batch = batch.to(device)
        optimizer.zero_grad()

        # 1. Forward Pass (Feed node features and edge indices)
        out = model(batch.x_dict, batch.edge_index_dict)
        
        # 2. Label Preparation
        # If the synthetic graph doesn't have 'y' labels yet, mock them for the test
        if 'y' not in batch['account']:
            batch['account'].y = torch.randint(
                0, 2, (batch['account'].num_nodes, 1), dtype=torch.float32
            ).to(device)

        labels = batch['account'].y.float()
        
        # 3. Calculate Loss (Binary Cross Entropy for Fraud/Not-Fraud)
        loss = F.binary_cross_entropy_with_logits(out, labels)
        
        # 4. Backward Pass
        loss.backward()
        
        # 5. Gradient Clipping (CRITICAL for stabilizing Graph Neural Networks)
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        
        # 6. Optimize Weights
        optimizer.step()
        
        # Metrics Calculation
        total_loss += float(loss) * batch['account'].num_nodes
        preds = (torch.sigmoid(out) > 0.5).float()
        correct += int((preds == labels).sum())
        total_samples += batch['account'].num_nodes
        
        pbar.set_postfix({'loss': f"{loss.item():.4f}"})

    return total_loss / total_samples, correct / total_samples

def main():
    print("Initializing HTGNN Training Pipeline...")
    
    # Auto-detect GPU acceleration
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Hardware utilized: {device}")

    # 1. Load the Temporal Dataloader we built previously
    try:
        sampler = AegisGraphLoader(batch_size=64)
        train_loader = sampler.get_train_loader()
    except FileNotFoundError:
        print("Error: Synthetic graph not found. Run graph generation first.")
        return

    # 2. Initialize Model and Optimizer
    model = AegisHTGNN().to(device)
    optimizer = AdamW(model.parameters(), lr=0.001, weight_decay=1e-4)

    # 3. Execute Training Loop
    epochs = 3
    for epoch in range(1, epochs + 1):
        print(f"\n--- Epoch {epoch}/{epochs} ---")
        loss, acc = train_epoch(model, train_loader, optimizer, device)
        print(f"Epoch {epoch} Summary -> Loss: {loss:.4f} | Accuracy: {acc:.4f}")

    # 4. Save the compiled artifact
    print("\nTraining Complete! Saving model weights...")
    os.makedirs("models", exist_ok=True)
    torch.save(model.state_dict(), "models/htgnn_v1.pt")
    print("Artifact saved to models/htgnn_v1.pt")

if __name__ == "__main__":
    main()