from .base import BaseConnector
from typing import Dict, List, Optional, Any
import logging
import boto3
import time
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

class AWSConnector(BaseConnector):
    """
    Connector for AWS APIs using boto3.
    
    Supports fetching:
    - IAM Users (and their active keys)
    - IAM Roles
    - S3 Buckets
    - Secrets Manager Secrets (metadata)
    """

    def __init__(self, task, subtask):
        super().__init__(task, subtask)
        self.client = None
        self.region = 'us-east-1'

    def get_base_url(self) -> str:
        return "https://aws.amazon.com"  # Not used directly with boto3

    def authenticate(self) -> None:
        """
        Configure boto3 client with credentials.
        """
        if not self.task.auth_config:
            raise ValueError("No auth_config found for AWS connector")

        aws_access_key = self.task.auth_config.get('aws_access_key')
        aws_secret_key = self.task.auth_config.get('aws_secret_key')
        self.region = self.task.auth_config.get('aws_region', 'us-east-1')

        if not aws_access_key or not aws_secret_key:
            raise ValueError("Missing AWS Access Key or Secret Key")

        # Determine service based on endpoint
        # e.g. /iam/users -> iam
        service_name = self.subtask.endpoint.split('/')[1]
        
        try:
            self.client = boto3.client(
                service_name,
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                region_name=self.region
            )
        except Exception as e:
            logger.error(f"[AWS] Failed to create boto3 client: {e}")
            raise

    def parse_items(self, response_data: Dict) -> List[Dict]:
        """Not used as we handle pagination internally via boto3 paginators"""
        return []

    def get_pagination_token(self, response_data: Dict) -> Optional[str]:
        """Not used as we handle pagination internally via boto3 paginators"""
        return None

    def fetch_all_pages(self) -> Dict[str, Any]:
        """
        Override fetch_all_pages to use boto3 paginators instead of manual loop.
        """
        logger.info(f"[{self.task.service}] Starting fetch_all_pages for {self.subtask.name}")
        self.authenticate()
        
        start_time = time.time()
        all_items = []
        
        endpoint_parts = self.subtask.endpoint.strip('/').split('/')
        resource_type = endpoint_parts[1]
        
        try:
            if resource_type == 'users':
                all_items = self._fetch_iam_users()
            elif resource_type == 'roles':
                all_items = self._fetch_iam_roles()
            elif resource_type == 'buckets':
                all_items = self._fetch_s3_buckets()
            elif resource_type == 'secrets':
                all_items = self._fetch_secrets()
            else:
                raise ValueError(f"Unknown resource type: {resource_type}")

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(f"[{self.task.service}] Completed: {len(all_items)} items in {duration_ms}ms")

            return {
                'items': all_items,
                'total_count': len(all_items),
                'pages_fetched': 1,  # Boto3 handles pages internally
                'duration_ms': duration_ms
            }

        except ClientError as e:
            logger.error(f"[{self.task.service}] AWS ClientError: {e}")
            raise
        except Exception as e:
            logger.error(f"[{self.task.service}] Unexpected error: {e}", exc_info=True)
            raise

    def _fetch_iam_users(self) -> List[Dict]:
        """Fetch all IAM users and their access key metadata."""
        paginator = self.client.get_paginator('list_users')
        users = []
        
        for page in paginator.paginate():
            for user in page['Users']:
                user_data = {
                    'UserName': user['UserName'],
                    'UserId': user['UserId'],
                    'Arn': user['Arn'],
                    'CreateDate': user['CreateDate'].isoformat(),
                    'PasswordLastUsed': user.get('PasswordLastUsed', '').isoformat() if user.get('PasswordLastUsed') else None,
                    'AccessKeys': []
                }
                
                # Fetch Access Keys for this user
                try:
                    keys_resp = self.client.list_access_keys(UserName=user['UserName'])
                    for key in keys_resp['AccessKeyMetadata']:
                        user_data['AccessKeys'].append({
                            'AccessKeyId': key['AccessKeyId'],
                            'Status': key['Status'],
                            'CreateDate': key['CreateDate'].isoformat()
                        })
                except Exception as e:
                    logger.warning(f"[AWS] Failed to list keys for user {user['UserName']}: {e}")
                
                users.append(user_data)
        
        return users

    def _fetch_iam_roles(self) -> List[Dict]:
        """Fetch IAM roles, filtering out AWS service roles if possible."""
        paginator = self.client.get_paginator('list_roles')
        roles = []
        
        for page in paginator.paginate():
            for role in page['Roles']:
                # Filter out standard service roles to reduce noise?
                # For now getting all, but marking type
                is_service_role = '/aws-service-role/' in role['Path']
                
                roles.append({
                    'RoleName': role['RoleName'],
                    'RoleId': role['RoleId'],
                    'Arn': role['Arn'],
                    'CreateDate': role['CreateDate'].isoformat(),
                    'Description': role.get('Description'),
                    'IsServiceRole': is_service_role
                })
        
        return roles

    def _fetch_s3_buckets(self) -> List[Dict]:
        """Fetch S3 buckets."""
        # list_buckets is not paginated by boto3 (returns all owned buckets)
        response = self.client.list_buckets()
        buckets = []
        
        for bucket in response['Buckets']:
            # Get location (optional, but good for inventory)
            try:
                # Need a client for specific bucket ops if region specific, 
                # but get_bucket_location works on general client usually
                loc_resp = self.client.get_bucket_location(Bucket=bucket['Name'])
                region = loc_resp['LocationConstraint'] or 'us-east-1'
            except:
                region = 'unknown'

            buckets.append({
                'Name': bucket['Name'],
                'CreationDate': bucket['CreationDate'].isoformat(),
                'Region': region
            })
            
        return buckets

    def _fetch_secrets(self) -> List[Dict]:
        """Fetch Secrets Manager secrets metadata."""
        paginator = self.client.get_paginator('list_secrets')
        secrets = []
        
        for page in paginator.paginate():
            for secret in page['SecretList']:
                secrets.append({
                    'Name': secret['Name'],
                    'Description': secret.get('Description'),
                    'LastChangedDate': secret.get('LastChangedDate', '').isoformat() if secret.get('LastChangedDate') else None,
                    'CreatedDate': secret.get('CreatedDate', '').isoformat() if secret.get('CreatedDate') else None,
                    'DeletedDate': secret.get('DeletedDate', '').isoformat() if secret.get('DeletedDate') else None,
                })
                
        return secrets
