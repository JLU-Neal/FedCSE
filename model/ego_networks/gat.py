import torch
import torch.nn.functional as F
from torch_geometric.nn import GATConv


class Net(torch.nn.Module):
    def __init__(self, in_channels, out_channels, dropout, heads = 2 ):
        super(Net, self).__init__()
        self.dropout = dropout
        self.conv1 = GATConv(in_channels, heads, heads= heads)
        # On the Pubmed dataset, use heads=8 in conv2.
        self.conv2 = GATConv(heads**2, out_channels, heads=1, concat=False)
    def forward(self, x, edge_index):
        
        x = F.elu(self.conv1(x, edge_index))
        x = F.dropout(x, p=self.dropout, training=self.training)
        x = self.conv2(x, edge_index)
        return F.log_softmax(x, dim=-1)

    def loss(self, pred, label):
        return F.nll_loss(pred, label)
