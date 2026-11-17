import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime
from src.connectors.aws import AWSConnector

class MockTask:
    def __init__(self):
        self.service = 'aws'
        self.auth_config = {
            'aws_access_key': 'AKIA_TEST',
            'aws_secret_key': 'SECRET_TEST',
            'aws_region': 'us-east-1'
        }

    @property
    def credentials(self):
        return self.auth_config

class MockSubtask:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.name = 'Test Subtask'

class TestAWSConnector(unittest.TestCase):

    def setUp(self):
        self.task = MockTask()

    @patch('boto3.client')
    def test_fetch_iam_users(self, mock_boto_client):
        # Setup mock client
        mock_iam = MagicMock()
        mock_boto_client.return_value = mock_iam
        
        # Setup paginator for list_users
        mock_paginator = MagicMock()
        mock_iam.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [{
            'Users': [{
                'UserName': 'test_user',
                'UserId': 'AIDATEST',
                'Arn': 'arn:aws:iam::123:user/test_user',
                'CreateDate': datetime(2023, 1, 1),
                'PasswordLastUsed': datetime(2023, 1, 2)
            }]
        }]
        
        # Setup list_access_keys
        mock_iam.list_access_keys.return_value = {
            'AccessKeyMetadata': [{
                'AccessKeyId': 'AKIA123',
                'Status': 'Active',
                'CreateDate': datetime(2023, 1, 1)
            }]
        }

        # Run Connector
        subtask = MockSubtask('/iam/users')
        connector = AWSConnector(self.task, subtask)
        result = connector.fetch_all_pages()
        
        # Verify
        self.assertEqual(len(result['items']), 1)
        user = result['items'][0]
        self.assertEqual(user['UserName'], 'test_user')
        self.assertEqual(len(user['AccessKeys']), 1)
        self.assertEqual(user['AccessKeys'][0]['AccessKeyId'], 'AKIA123')

    @patch('boto3.client')
    def test_fetch_s3_buckets(self, mock_boto_client):
        # Setup mock client
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3
        
        mock_s3.list_buckets.return_value = {
            'Buckets': [{
                'Name': 'test-bucket',
                'CreationDate': datetime(2023, 1, 1)
            }]
        }
        mock_s3.get_bucket_location.return_value = {'LocationConstraint': 'us-west-2'}

        # Run Connector
        subtask = MockSubtask('/s3/buckets')
        connector = AWSConnector(self.task, subtask)
        result = connector.fetch_all_pages()
        
        # Verify
        self.assertEqual(len(result['items']), 1)
        bucket = result['items'][0]
        self.assertEqual(bucket['Name'], 'test-bucket')
        self.assertEqual(bucket['Region'], 'us-west-2')

if __name__ == '__main__':
    unittest.main()
