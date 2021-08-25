import logging

import numpy as np
import torch
import torch.nn.functional as F

import wandb

from sklearn.metrics import average_precision_score, roc_auc_score, mean_absolute_error

from FedML.fedml_core.trainer.model_trainer import ModelTrainer


class FedSubgraphLPTrainer(ModelTrainer):
    def get_model_params(self):
        return self.model.cpu().state_dict()

    def set_model_params(self, model_parameters):
        logging.info("set_model_params")
        self.model.load_state_dict(model_parameters)

    def train(self, train_data, device, args):
        model = self.model

        if args.metric == "MAE":
            self.metric_fn = mean_absolute_error

        model.to(device)
        model.train()
        if args.client_optimizer == "sgd":
            optimizer = torch.optim.SGD(
                filter(lambda p: p.requires_grad, model.parameters()),
                lr=args.lr,
                weight_decay=args.wd,
            )
        else:
            optimizer = torch.optim.Adam(
                filter(lambda p: p.requires_grad, model.parameters()),
                lr=args.lr,
                weight_decay=args.wd,
            )

        max_test_score = 0
        best_model_params = {}
        for epoch in range(args.epochs):

            for idx_batch, batch in enumerate(train_data):

                batch.to(device)
                optimizer.zero_grad()

                z = model.encode(batch.x, batch.edge_train)
                link_logits = model.decode(z, batch.edge_train)
                link_labels = batch.label_train
                loss = F.mse_loss(link_logits, link_labels)
                loss.backward()
                optimizer.step()

            if train_data is not None:
                test_score, _ = self.test(
                    train_data, device, val=True, metric=self.metric_fn
                )
                print(
                    "Epoch = {}, Iter = {}/{}: Test score = {}".format(
                        epoch, idx_batch + 1, len(train_data), test_score
                    )
                )
                if test_score < max_test_score:
                    max_test_score = test_score
                    best_model_params = {
                        k: v.cpu() for k, v in model.state_dict().items()
                    }
                print("Current best = {}".format(max_test_score))

        return max_test_score, best_model_params

    def test(self, test_data, device, val=True, metric=mean_absolute_error):
        logging.info("----------test--------")
        model = self.model
        model.eval()
        model.to(device)
        metric = metric

        for batch in test_data:
            batch.to(device)
            with torch.no_grad():
                train_z = model.encode(batch.x, batch.edge_train)
                if val == True:
                    link_logits = model.decode(train_z, batch.edge_val)
                else:
                    link_logits = model.decode(train_z, batch.edge_test)

                if val == True:
                    link_labels = batch.label_val
                else:
                    link_labels = batch.label_test
                score = metric(link_labels.cpu(), link_logits.cpu())
        return score, model

    def test_on_the_server(
        self, train_data_local_dict, test_data_local_dict, device, args=None
    ) -> bool:
        logging.info("----------test_on_the_server--------")

        model_list, score_list = [], []
        for client_idx in test_data_local_dict.keys():
            test_data = test_data_local_dict[client_idx]
            score, model = self.test(test_data, device, val=False)
            for idx in range(len(model_list)):
                self._compare_models(model, model_list[idx])
            model_list.append(model)
            score_list.append(score)
            logging.info(
                "Client {}, Test {} = {}".format(client_idx, args.metric, score)
            )
            wandb.log({"Client {} Test/{}".format(client_idx, args.metric): score})

        avg_score = np.mean(np.array(score_list))
        logging.info("Test {} = {}".format(args.metric, avg_score))
        wandb.log({"Test/{}".format(args.metric): avg_score})

        return True

    def _compare_models(self, model_1, model_2):
        models_differ = 0
        for key_item_1, key_item_2 in zip(
            model_1.state_dict().items(), model_2.state_dict().items()
        ):
            if torch.equal(key_item_1[1], key_item_2[1]):
                pass
            else:
                models_differ += 1
                if key_item_1[0] == key_item_2[0]:
                    logging.info("Mismatch found at", key_item_1[0])
                else:
                    raise Exception
        if models_differ == 0:
            logging.info("Models match perfectly! :)")

    def get_link_labels(self, pos_edge_index, neg_edge_index, device):
        num_links = pos_edge_index.size(1) + neg_edge_index.size(1)
        link_labels = torch.zeros(num_links, dtype=torch.float, device=device)
        link_labels[: pos_edge_index.size(1)] = 1.0
        return link_labels
